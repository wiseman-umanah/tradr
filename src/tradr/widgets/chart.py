from __future__ import annotations

from threading import Lock, Thread
from typing import Any

import pandas as pd
from rich.text import Text
from textual import work
from textual.app import RenderResult
from textual_plotext import PlotextPlot

from tradr.market import extract_ohlcv, get_ohlcv
from tradr.trading import get_trading_config

try:
    from alpaca.data.live.stock import StockDataStream
except ModuleNotFoundError:
    StockDataStream = None  # type: ignore[assignment]

DEFAULT_SYMBOL = "AAPL"
DEFAULT_PERIOD = "1d"
DEFAULT_INTERVAL = "5m"
REFRESH_SECONDS = 30
MAX_CANDLES = 240
VALID_PERIODS = {
    "1d",
    "5d",
    "1mo",
    "3mo",
    "6mo",
    "1y",
    "2y",
    "5y",
    "10y",
    "ytd",
    "max",
}
VALID_INTERVALS = {
    "1m",
    "2m",
    "5m",
    "15m",
    "30m",
    "60m",
    "90m",
    "1h",
    "1d",
    "5d",
    "1wk",
    "1mo",
    "3mo",
}
LIVE_SUPPORTED_INTERVALS = VALID_INTERVALS
PANDAS_RULES = {
    "1m": "1min",
    "2m": "2min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "60m": "60min",
    "1h": "1h",
    "90m": "90min",
    "1d": "1D",
    "5d": "5D",
    "1wk": "1W",
    "1mo": "1ME",
    "3mo": "3ME",
}


def _normalize(value: str, allowed: set[str], fallback: str) -> str:
    """Return value if it is allowed, otherwise fallback."""
    return value if value in allowed else fallback


def _resample_ohlcv(data: pd.DataFrame, interval: str) -> pd.DataFrame:
    if data.empty:
        return data
    rule = PANDAS_RULES.get(interval)
    if rule is None:
        return data
    frame = data.sort_index()
    resampled = frame.resample(rule, label="right", closed="right").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    )
    return resampled.dropna(subset=["Open", "High", "Low", "Close"])


def _minute_frame_from_bar(bar: Any) -> pd.DataFrame:
    timestamp = pd.to_datetime(getattr(bar, "timestamp"), utc=True)
    frame = pd.DataFrame(
        [
            {
                "Date": timestamp,
                "Open": float(getattr(bar, "open")),
                "High": float(getattr(bar, "high")),
                "Low": float(getattr(bar, "low")),
                "Close": float(getattr(bar, "close")),
                "Volume": float(getattr(bar, "volume", 0)),
            }
        ]
    )
    return frame.set_index("Date")


class Chart(PlotextPlot):
    """Handle the chart"""
    can_focus = True

    def __init__(self) -> None:
        super().__init__(id="chart")
        self.symbol = DEFAULT_SYMBOL
        self.period = DEFAULT_PERIOD
        self.interval = DEFAULT_INTERVAL
        self._error: str | None = None
        self._history = pd.DataFrame()
        self._live_minutes = pd.DataFrame()
        self._stream: StockDataStream | None = None  # type: ignore[valid-type]
        self._stream_thread: Thread | None = None
        self._stream_lock = Lock()
        self._stream_generation = 0
        self._stream_active = False
        # follow the application's current theme (auto = textual palette)
        self.theme = "auto"

    def on_mount(self) -> None:
        self.loading = True
        self.set_interval(REFRESH_SECONDS, self.refresh_chart)
        self.call_after_refresh(self.refresh_chart)

    def on_unmount(self) -> None:
        self._stop_stream()

    def on_resize(self, event) -> None:
        self.refresh()

    def render(self) -> RenderResult:
        if self._error:
            return Text.from_markup(f"[red]Failed to load chart: {self._error}[/red]")
        return super().render()

    def refresh_chart(self) -> None:
        """Kick off a background refresh."""
        if self._stream_active:
            self._redraw_live_chart()
            return
        self.load_chart()

    @work(thread=True)
    def load_chart(self) -> None:
        try:
            width = self.size.width or 100
            height = self.size.height or 30

            self.log(
                f"Widget size: {width} x {height} | "
                f"{self.symbol} {self.period} @ {self.interval}"
            )

            data = get_ohlcv(
                self.symbol,
                self.period,
                self.interval,
                max_candles=MAX_CANDLES,
            )
            self._history = data.copy()
            self._live_minutes = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
            self._sync_stream()
            ohlcv = extract_ohlcv(self._display_data())

            plot = self.plt
            plot.clf()
            plot.date_form("d/m/Y H:M")
            plot.plotsize(width, height)
            plot.title(f"{self.symbol} — {self.period}")
            plot.candlestick(ohlcv["dates"], ohlcv)

            self._error = None
            self.app.call_from_thread(self.refresh)
        except Exception as e:
            self._error = str(e)
            self.app.call_from_thread(self.refresh)
        finally:
            self.app.call_from_thread(setattr, self, "loading", False)

    def _display_data(self) -> pd.DataFrame:
        data = self._history.copy()
        if self._live_minutes.empty:
            return data.tail(MAX_CANDLES)
        live = _resample_ohlcv(self._live_minutes, self.interval)
        if live.empty:
            return data.tail(MAX_CANDLES)
        combined = pd.concat([data, live])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()
        return combined.tail(MAX_CANDLES)

    def _sync_stream(self) -> None:
        self._stop_stream()
        if not self._can_stream_live():
            return

        config = get_trading_config()
        api_key = config.get("api_key")
        secret_key = config.get("secret_key")
        if not api_key or not secret_key:
            return

        generation = self._stream_generation + 1
        self._stream_generation = generation
        stream = StockDataStream(api_key, secret_key)  # type: ignore[operator]

        async def handle_bar(bar: Any) -> None:
            if generation != self._stream_generation:
                return
            self._handle_live_bar(bar)

        stream.subscribe_bars(handle_bar, self.symbol)
        if hasattr(stream, "subscribe_updated_bars"):
            stream.subscribe_updated_bars(handle_bar, self.symbol)

        thread = Thread(target=stream.run, name=f"alpaca-stock-stream-{self.symbol}", daemon=True)
        with self._stream_lock:
            self._stream = stream
            self._stream_thread = thread
            self._stream_active = True
        thread.start()

    def _stop_stream(self) -> None:
        with self._stream_lock:
            stream = self._stream
            thread = self._stream_thread
            self._stream = None
            self._stream_thread = None
            self._stream_active = False
            self._stream_generation += 1
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=1)

    def _can_stream_live(self) -> bool:
        return StockDataStream is not None and self.interval in LIVE_SUPPORTED_INTERVALS

    def _handle_live_bar(self, bar: Any) -> None:
        try:
            minute = _minute_frame_from_bar(bar)
            self._live_minutes = pd.concat([self._live_minutes, minute])
            self._live_minutes = self._live_minutes[~self._live_minutes.index.duplicated(keep="last")]
            self._live_minutes = self._live_minutes.sort_index().tail(MAX_CANDLES * 10)
            self.app.call_from_thread(self._redraw_live_chart)
        except Exception as exc:
            self._error = str(exc)
            self.app.call_from_thread(self.refresh)

    def _redraw_live_chart(self) -> None:
        try:
            width = self.size.width or 100
            height = self.size.height or 30
            ohlcv = extract_ohlcv(self._display_data())
            plot = self.plt
            plot.clf()
            plot.date_form("d/m/Y H:M")
            plot.plotsize(width, height)
            plot.title(f"{self.symbol} — {self.period}")
            plot.candlestick(ohlcv["dates"], ohlcv)
            self._error = None
        finally:
            self.refresh()

    def update_symbol(
        self,
        symbol: str,
        period: str | None = None,
        interval: str | None = None,
    ) -> None:
        """Call this from outside to update the chart"""
        self.symbol = symbol
        if period is not None:
            normalized_period = _normalize(period, VALID_PERIODS, DEFAULT_PERIOD)
            if normalized_period != period:
                self.log(
                    f"Invalid period '{period}' received, using '{normalized_period}'"
                )
            self.period = normalized_period
        if interval is not None:
            normalized_interval = _normalize(interval, VALID_INTERVALS, DEFAULT_INTERVAL)
            if normalized_interval != interval:
                self.log(
                    f"Invalid interval '{interval}' received, using '{normalized_interval}'"
                )
            self.interval = normalized_interval
        self.refresh_chart()
