from textual.containers import Vertical
from textual.widgets import Input, RichLog
from textual.app import ComposeResult
from textual.widget import Widget
from textual import on


class AiChat(Widget):
    """AI + Command Terminal"""
    can_focus = True

    def __init__(self) -> None:
        super().__init__(id="terminal")

    def compose(self) -> ComposeResult:
        self.output = RichLog(id="output", highlight=True, markup=True)
        self.input = Input(placeholder="Chat/Type commands here", id="input", compact=True)

        yield self.output
        yield self.input

    def on_mount(self) -> None:
        self.query_one("#input", Input).focus()


    # COMMAND HANDLER
    def run_command(self, text: str) -> None:
        parts = text.strip().split()

        if not parts:
            return

        cmd = parts[0]
        args = parts[1:]

        commands = {
            "analyze": self.cmd_analyze,
            "buy": self.cmd_buy,
            "sell": self.cmd_sell,
            "help": self.cmd_help,
        }

        if cmd in commands:
            commands[cmd](args)
        else:
            self.chat_with_ai(text)



    # COMMAND IMPLEMENTATIONS
    def cmd_analyze(self, args):
        if not args:
            self.output.write("[red]Usage: analyze <symbol>[/red]")
            return

        symbol = args[0]
        self.output.write(f"[cyan]Analyzing {symbol}...[/cyan]")

    def cmd_buy(self, args):
        if len(args) < 2:
            self.output.write("[red]Usage: buy <symbol> <qty>[/red]")
            return

        symbol, qty = args
        self.output.write(f"[green]Buying {qty} shares of {symbol}[/green]")

    def cmd_sell(self, args):
        if len(args) < 2:
            self.output.write("[red]Usage: sell <symbol> <qty>[/red]")
            return

        symbol, qty = args
        self.output.write(f"[yellow]Selling {qty} shares of {symbol}[/yellow]")

    def cmd_help(self, args):
        self.output.write("[bold]Available commands:[/bold]")
        self.output.write(" - analyze <symbol>")
        self.output.write(" - buy <symbol> <qty>")
        self.output.write(" - sell <symbol> <qty>")
        self.output.write(" - help")


    # AI FALLBACK
    def chat_with_ai(self, text: str):
        self.output.write(f"[magenta]AI:[/magenta] Thinking about '{text}'...")


    # INPUT HANDLER
    @on(Input.Submitted)
    def handle_input(self, event: Input.Submitted) -> None:
        text = event.value.strip()

        if not text:
            return

        # display user input like terminal
        self.output.write(text)

        # process command
        self.run_command(text)

        # clear input
        event.input.value = ""
