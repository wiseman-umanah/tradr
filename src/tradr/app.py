from textual.app import App


class TradrApp(App):
    """Terminal Trader App"""

    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]

    def action_toggle_dark(self) -> None:
        self.theme = (
                "textual-dark" if self.theme == "textual-light" else "textual-light"
                )


