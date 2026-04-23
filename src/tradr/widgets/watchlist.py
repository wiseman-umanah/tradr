from __future__ import annotations
import json
from pathlib import Path
from rich.text import Text
from textual import work
from textual.widgets import DataTable
from tradr.market import get_snapshots, load_symbol_list
from platformdirs import user_config_dir

REFRESH_SECONDS = 30
SYMBOL_REFRESH_SECONDS = 86400  # 24 hours
DISPLAY_SIZE = 50  # symbols visible at a time
ROTATION_SECONDS = 300  # rotate pool every 5 mins
CONFIG_DIR = Path(user_config_dir(appname="tradr", appauthor="wiseman-umanah", ensure_exists=True))
WATCHLIST_FILE = CONFIG_DIR / "watchlist.json"


def _load_pinned_symbols() -> list[str]:
    try:
        with WATCHLIST_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return [str(symbol).upper().strip() for symbol in data.get("pinned", []) if symbol]
    except Exception:
        return []


def _save_pinned_symbols(symbols: list[str]) -> None:
    with WATCHLIST_FILE.open("w", encoding="utf-8") as file:
        json.dump({"pinned": symbols}, file)

class Watchlist(DataTable):
    """Scrollable watchlist that streams price updates."""

    def __init__(self) -> None:
        super().__init__(id="watchlist")
        self.all_symbols: list[str] = []
        self.pinned_symbols: list[str] = _load_pinned_symbols()
        self.symbols: list[str] = []
        self._row_keys: set[str] = set()
        self._column_keys: list = []
        self._price_cache: dict[str, tuple] = {}
        self._pool_offset: int = 0
        self.loading = True

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.show_header = True
        self._column_keys = list(
            self.add_columns("Symbol", "Price", "Change", "P/L")
        )
        self._show_placeholder("Loading symbols…")
        self._fetch_symbols()
        self.set_interval(REFRESH_SECONDS, self.load_watchlist)
        self.set_interval(ROTATION_SECONDS, self._rotate_pool)
        self.set_interval(SYMBOL_REFRESH_SECONDS, self._fetch_symbols)

    @work(thread=True)
    def _fetch_symbols(self) -> None:
        """Download or load cached symbol list"""
        symbols = load_symbol_list()
        if symbols:
            self.all_symbols = symbols
            self._update_display_symbols()
            self.app.call_from_thread(self.load_watchlist)
        else:
            self.app.call_from_thread(
                self._show_placeholder, "Failed to load symbols"
            )

    def _update_display_symbols(self) -> None:
        """
        Build display list:
        pinned symbols first then
        rotating slice from full pool
        """
        pool = [s for s in self.all_symbols if s not in self.pinned_symbols]
        start = self._pool_offset % max(len(pool), 1)
        end = start + DISPLAY_SIZE
        # wrap around if we hit the end of the pool
        if end <= len(pool):
            rotating = pool[start:end]
        else:
            rotating = pool[start:] + pool[:end - len(pool)]
        self.symbols = self.pinned_symbols + rotating

    def _rotate_pool(self) -> None:
        """Advance the pool offset to show different symbols"""
        pool_size = max(len(self.all_symbols) - len(self.pinned_symbols), 1)
        self._pool_offset = (self._pool_offset + DISPLAY_SIZE) % pool_size
        self._update_display_symbols()
        self._remove_stale_rows()
        self.load_watchlist()

    def pin_symbol(self, symbol: str) -> bool:
        """Pin a user requested symbol to the top of the watchlist"""
        symbol = symbol.upper().strip()
        if symbol in self.pinned_symbols:
            return False
        self.pinned_symbols.insert(0, symbol)
        _save_pinned_symbols(self.pinned_symbols)
        self._update_display_symbols()
        self.load_watchlist()
        return True

    def unpin_symbol(self, symbol: str) -> bool:
        """Remove a pinned symbol"""
        symbol = symbol.upper().strip()
        if symbol not in self.pinned_symbols:
            return False
        self.pinned_symbols.remove(symbol)
        _save_pinned_symbols(self.pinned_symbols)
        self._update_display_symbols()
        self._remove_stale_rows()
        self.load_watchlist()
        return True

    @work(thread=True)
    def load_watchlist(self) -> None:
        """Fetch prices for current display symbols."""
        if not self.symbols:
            return
        self.app.call_from_thread(self._clear_placeholder)
        snapshots = get_snapshots(self.symbols)
        for symbol in self.symbols:
            row = self._row_from_snapshot(symbol, snapshots.get(symbol))
            if row is not None:
                self._price_cache[symbol] = row
                self.app.call_from_thread(self._upsert_row, symbol, row)
            else:
                cached = self._price_cache.get(symbol)
                if cached:
                    self.app.call_from_thread(self._upsert_row, symbol, cached)
                else:
                    fallback = (
                        Text(symbol, style="dim"),
                        Text("N/A", style="dim"),
                        Text("N/A", style="dim"),
                        Text("N/A", style="dim"),
                    )
                    self.app.call_from_thread(self._upsert_row, symbol, fallback)
        self.app.call_from_thread(setattr, self, "loading", False)

    def _row_from_snapshot(self, symbol: str, snapshot: dict | None) -> tuple | None:
        """Build a table row from a market snapshot."""
        if snapshot is None:
            return None
        price = snapshot.get("price")
        change_pct = snapshot.get("change_pct")
        profit_loss = snapshot.get("change")
        if price is None or change_pct is None or profit_loss is None:
            return None
        color = "green" if change_pct >= 0 else "red"
        arrow = "▲" if change_pct >= 0 else "▼"
        return (
            Text(symbol, style="bold"),
            Text(f"${price:.2f}", style=color),
            Text(f"{arrow} {abs(change_pct):.2f}%", style=color),
            Text(f"{profit_loss:+.2f}", style=color),
        )

    def _remove_stale_rows(self) -> None:
        valid = set(self.symbols)
        for key in list(self._row_keys):
            if key not in valid:
                self.remove_row(key)
                self._row_keys.discard(key)

    def _show_placeholder(self, message: str) -> None:
        self.clear()
        self._row_keys.clear()
        self.add_row(
            Text(message, style="dim"),
            Text("-", style="dim"),
            Text("-", style="dim"),
            Text("-", style="dim"),
            key="__placeholder__",
        )
        self._row_keys.add("__placeholder__")

    def _clear_placeholder(self) -> None:
        if "__placeholder__" in self._row_keys:
            self.remove_row("__placeholder__")
            self._row_keys.discard("__placeholder__")

    def _upsert_row(self, key: str, row: tuple) -> None:
        if key in self._row_keys:
            for col_key, value in zip(self._column_keys, row):
                self.update_cell(key, col_key, value)
        else:
            self.add_row(*row, key=key)
            self._row_keys.add(key)
