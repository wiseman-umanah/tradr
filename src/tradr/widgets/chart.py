from rich.text import Text
from textual.app import RenderResult
from textual import work
from textual_plotext import PlotextPlot
from tradr.market import get_ohlcv, extract_ohlcv

DEFAULT_SYMBOL = "AAPL"
DEFAULT_PERIOD = "1d"
DEFAULT_INTERVAL = "5m"
REFRESH_SECONDS = 30


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
        self.loading = True
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

            data = get_ohlcv(self.symbol, self.period, self.interval)
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
            self.period = period
        if interval is not None:
            self.interval = interval
        self.refresh_chart()
