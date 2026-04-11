from rich.text import Text
from textual.app import RenderResult
from textual import work
from textual_plotext import PlotextPlot
from tradr.market import get_ohlcv, extract_ohlcv

DEFAULT_SYMBOL = "AAPL"
DEFAULT_PERIOD = "5d"
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


def _normalize(value: str, allowed: set[str], fallback: str) -> str:
    """Return value if it is allowed, otherwise fallback."""
    return value if value in allowed else fallback


class Chart(PlotextPlot):
    """Handle the chart"""
    can_focus = True

    def __init__(self) -> None:
        super().__init__(id="chart")
        self.symbol = DEFAULT_SYMBOL
        self.period = DEFAULT_PERIOD
        self.interval = DEFAULT_INTERVAL
        self._error: str | None = None
        self.theme = "dark"

    def on_mount(self) -> None:
        self.loading = True
        self.set_interval(REFRESH_SECONDS, self.refresh_chart)
        self.call_after_refresh(self.refresh_chart)

    def on_resize(self, event) -> None:
        self.refresh()

    def render(self) -> RenderResult:
        if self._error:
            return Text.from_markup(f"[red]Failed to load chart: {self._error}[/red]")
        return super().render()

    def refresh_chart(self) -> None:
        """Kick off a background refresh."""
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
            ohlcv = extract_ohlcv(data)

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
