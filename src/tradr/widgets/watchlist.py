from rich.table import Table
from textual.widgets import Static
from textual import work
from textual.reactive import reactive


class Watchlist(Static):
    """Handle the Watchlist """
    can_focus=True

    def __init__(self) -> None:
        super().__init__(id="watchlist")

    count = reactive(0)

    def on_mount(self) -> None:
        table = Table(
                "Symbol", "Price", 
                "Change", "P/L", 
                title="Watchlist", expand=True,
                show_edge=True, pad_edge=True, box=None, show_lines=False
            )

        self.update(table)


        @work
        async def load_watchlist(self) -> None:
            pass

