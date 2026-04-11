from rich.table import Table
from rich.text import Text
from textual.widgets import Static
from textual import work
from textual.reactive import reactive
from tradr.market import get_trending_symbols
import yfinance as yf


PAGE_SIZE = 10


class Watchlist(Static):
    """Handle the Watchlist """
    can_focus=True
    current_page = reactive(0)

    def __init__(self) -> None:
        super().__init__(id="watchlist")

    def on_mount(self) -> None:
        self.loading = True
        self.symbols = get_trending_symbols()
        self.render_empty_table()
        self.load_watchlist()
        self.set_interval(30, self.load_watchlist)
        self.set_interval(10, self.next_page)


    def render_empty_table(self) -> None:
        table = Table(
            "Symbol", "Price", "Change", "P/L",
            title="Watchlist", expand=True,
            show_edge=True, pad_edge=True,
            box=None, show_lines=False
        )
        self.update(table)


    def next_page(self) -> None:
        if not self.symbols:
            return
        total_pages = (len(self.symbols) + PAGE_SIZE - 1) // PAGE_SIZE
        self.current_page = (self.current_page + 1) % total_pages


    def watch_current_page(self, page: int) -> None:
        self.load_watchlist()


    @work(thread=True)
    def load_watchlist(self) -> None:
        start = self.current_page * PAGE_SIZE
        end = start + PAGE_SIZE
        page_symbols = self.symbols[start:end]

        table = Table(
                "Symbol", "Price",
                "Change", "P/L",
                title="Watchlist", expand=True,
                show_edge=True, pad_edge=True, box=None, show_lines=False
            )

        for symbol in page_symbols:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.fast_info

                price = info.last_price
                prev_close = info.previous_close
                change = ((price - prev_close) / prev_close) * 100
                pl = price - prev_close

                # color based on direction
                color = "green" if change >= 0 else "red"
                arrow = "▲" if change >= 0 else "▼"

                table.add_row(
                    Text(symbol, style="bold"),
                    Text(f"${price:.2f}", style=color),
                    Text(f"{arrow} {abs(change):.2f}%", style=color),
                    Text(f"{'+' if pl >= 0 else ''}{pl:.2f}", style=color),
                )
            except Exception:
                table.add_row(
                    Text(symbol, style="dim"),
                    Text("N/A", style="dim"),
                    Text("N/A", style="dim"),
                    Text("N/A", style="dim"),
                )
        self.app.call_from_thread(setattr, self, 'loading', False)
        self.app.call_from_thread(self.update, table)


