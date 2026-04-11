from textual.app import RenderResult
from textual.widgets import Static


class Chart(Static, can_focus=True):
    """Handle the chart"""
    def __init__(self) -> None:
        super().__init__(id="chart")


    def render(self) -> RenderResult:
        return "CHart handler"


