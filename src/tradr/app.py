from textual.app import App, ComposeResult
from textual.widgets import Static, Header, Footer
from textual.containers import Vertical
from .widgets.ai import AiChat
from .widgets.chart import Chart
from .widgets.watchlist import Watchlist



class TradrApp(App):
    """Terminal Trader App"""
    CSS_PATH = "styles/layout.tcss"

    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]

    def action_toggle_dark(self) -> None:
        self.theme = (
                "textual-dark" if self.theme == "textual-light" else "textual-light"
                )

    def compose(self) -> ComposeResult:
        """Terminal Design"""
        yield Header()
        with Vertical():
            yield Chart()
            yield AiChat()
        yield Watchlist()
        yield Footer()


