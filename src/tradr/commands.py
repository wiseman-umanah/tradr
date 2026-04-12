from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence, TYPE_CHECKING

import yfinance as yf
from textual.app import App

from tradr.market import get_ohlcv
from tradr import groq
from tradr.widgets.chart import Chart
from tradr.widgets.watchlist import Watchlist

if TYPE_CHECKING:
    from tradr.widgets.ai import AiChat


@dataclass(slots=True)
class CommandResponse:
    """Normalized response from a command handler."""

    message: str
    success: bool = True

    @classmethod
    def ok(cls, message: str) -> "CommandResponse":
        return cls(message=message, success=True)

    @classmethod
    def error(cls, message: str) -> "CommandResponse":
        return cls(message=f"[red]{message}[/red]", success=False)


@dataclass(slots=True)
class CommandContext:
    """Context passed to each command handler."""

    app: App
    chat: "AiChat"

    def get_chart(self) -> Chart | None:
        try:
            return self.app.query_one("#chart", Chart)
        except Exception:
            return None

    def get_watchlist(self) -> Watchlist | None:
        try:
            return self.app.query_one("#watchlist", Watchlist)
        except Exception:
            return None


Handler = Callable[[CommandContext, Sequence[str]], CommandResponse]


@dataclass(slots=True)
class Command:
    """Command metadata."""

    name: str
    description: str
    usage: str
    handler: Handler
    aliases: tuple[str, ...] = ()


def analyze_stock(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    if not args:
        return CommandResponse.error("Usage: analyze <symbol>")

    symbol = args[0].upper()
    try:
        ticker = yf.Ticker(symbol)
        fast = ticker.fast_info
        price = fast.last_price
        prev_close = fast.previous_close or price
        if price is None:
            raise ValueError("price unavailable")
        change_pct = ((price - prev_close) / prev_close) * 100 if prev_close else 0
        high_52w = fast.year_high
        low_52w = fast.year_low

        ohlcv = get_ohlcv(symbol, period="1mo", interval="1d", max_candles=5)
        avg_volume = (
            int(ohlcv["volume"].tail(5).mean()) if not ohlcv.empty else fast.ten_day_average_volume
        )
    except Exception as exc:
        return CommandResponse.error(f"Failed to analyze {symbol}: {exc}")

    arrow = "▲" if change_pct >= 0 else "▼"
    color = "green" if change_pct >= 0 else "red"
    change_text = f"[{color}]{arrow} {abs(change_pct):.2f}%[/{color}]"
    lines = [
        f"[cyan]{symbol}[/cyan] snapshot:",
        f"  Price: [bold]{price:.2f}[/bold] ({change_text})",
        f"  52w Range: {low_52w:.2f} — {high_52w:.2f}" if high_52w and low_52w else "",
        f"  Avg Volume: {avg_volume:,}" if avg_volume else "",
    ]
    message = "\n".join(line for line in lines if line)
    return CommandResponse.ok(message)


def watch_stock(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    if not args:
        return CommandResponse.error("Usage: watch <symbol>")

    symbol = args[0].upper()
    watchlist = context.get_watchlist()
    if watchlist is None:
        return CommandResponse.error("Watchlist widget is not available.")

    added = watchlist.pin_symbol(symbol)
    if added:
        return CommandResponse.ok(f"Pinned [bold]{symbol}[/bold] to the watchlist.")
    return CommandResponse.ok(f"[yellow]{symbol}[/yellow] is already pinned.")


def unwatch_stock(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    if not args:
        return CommandResponse.error("Usage: unwatch <symbol>")

    symbol = args[0].upper()
    watchlist = context.get_watchlist()
    if watchlist is None:
        return CommandResponse.error("Watchlist widget is not available.")

    removed = watchlist.unpin_symbol(symbol)
    if removed:
        return CommandResponse.ok(f"Removed [bold]{symbol}[/bold] from pinned symbols.")
    return CommandResponse.error(f"{symbol} is not pinned.")


def update_chart(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    if not args:
        return CommandResponse.error("Usage: chart <symbol> [period] [interval]")

    symbol = args[0].upper()
    period = args[1] if len(args) > 1 else None
    interval = args[2] if len(args) > 2 else None

    chart = context.get_chart()
    if chart is None:
        return CommandResponse.error("Chart widget is not available.")

    chart.update_symbol(symbol, period=period, interval=interval)
    return CommandResponse.ok(
        f"Updating chart to [bold]{symbol}[/bold]"
        + (f" · period={period}" if period else "")
        + (f" · interval={interval}" if interval else "")
    )


def clear_chat_history(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    context.chat.clear_history(clear_log=True)
    return CommandResponse.ok("Cleared chat history.")


def list_commands(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    lines = ["[bold]Available commands[/bold]:"]
    for command in COMMANDS.values():
        alias_note = f" (alias: {', '.join(command.aliases)})" if command.aliases else ""
        lines.append(
            f"[cyan]{command.name}[/cyan]{alias_note} — {command.description} "
            f"[dim]{command.usage}[/dim]"
        )
    return CommandResponse.ok("\n".join(lines))


def buy_stock(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    if len(args) < 2:
        return CommandResponse.error("Usage: buy <symbol> <qty>")
    symbol = args[0].upper()
    try:
        qty = float(args[1])
    except ValueError:
        return CommandResponse.error("Quantity must be numeric.")
    return CommandResponse.ok(f"Virtual order: buy {qty:g} shares of [bold]{symbol}[/bold].")


def sell_stock(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    if len(args) < 2:
        return CommandResponse.error("Usage: sell <symbol> <qty>")
    symbol = args[0].upper()
    try:
        qty = float(args[1])
    except ValueError:
        return CommandResponse.error("Quantity must be numeric.")
    return CommandResponse.ok(f"Virtual order: sell {qty:g} shares of [bold]{symbol}[/bold].")


def set_api_key(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    if len(args) != 1:
        return CommandResponse.error("Usage: set-key <GROQ_API_KEY>")
    api_key = args[0].strip()
    try:
        groq.save_api_key(api_key)
        groq.init_client(api_key)
        context.chat.ai_ready = True
        return CommandResponse.ok("Groq API key saved and validated.")
    except ValueError as exc:
        return CommandResponse.error(str(exc))
    except Exception as exc:
        return CommandResponse.error(f"Failed to save key: {exc}")


def about_app(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    lines = [
        "[bold]Tradr[/bold] — a terminal trading desk.",
        "Built by [cyan]Wiseman Umanah[/cyan] (@wiseman-umanah).",
        "Features candlestick charts, AI chat, and a live watchlist.",
        "GitHub: https://github.com/wiseman-umanah",
    ]
    return CommandResponse.ok("\n".join(lines))


COMMANDS: dict[str, Command] = {
    "help": Command(
        name="help",
        description="Show available commands",
        usage="help",
        handler=list_commands,
        aliases=("?",),
    ),
    "analyze": Command(
        name="analyze",
        description="Show a quick summary for a symbol",
        usage="analyze <symbol>",
        handler=analyze_stock,
    ),
    "watch": Command(
        name="watch",
        description="Pin a symbol to the watchlist",
        usage="watch <symbol>",
        handler=watch_stock,
    ),
    "unwatch": Command(
        name="unwatch",
        description="Remove a symbol from pinned watchlist items",
        usage="unwatch <symbol>",
        handler=unwatch_stock,
    ),
    "chart": Command(
        name="chart",
        description="Update the chart to a symbol/timeframe",
        usage="chart <symbol> [period] [interval]",
        handler=update_chart,
        aliases=("setchart",),
    ),
    "clear": Command(
        name="clear",
        description="Clear chat history",
        usage="clear",
        handler=clear_chat_history,
    ),
    "buy": Command(
        name="buy",
        description="Record a virtual buy order",
        usage="buy <symbol> <qty>",
        handler=buy_stock,
    ),
    "sell": Command(
        name="sell",
        description="Record a virtual sell order",
        usage="sell <symbol> <qty>",
        handler=sell_stock,
    ),
    "set-key": Command(
        name="set-key",
        description="Validate and store Groq API key",
        usage="set-key <GROQ_API_KEY>",
        handler=set_api_key,
    ),
    "about": Command(
        name="about",
        description="About the app and author",
        usage="about",
        handler=about_app,
    ),
}


def iter_commands() -> Iterable[Command]:
    return COMMANDS.values()


def find_command(name: str) -> Command | None:
    target = name.lower()
    if target in COMMANDS:
        return COMMANDS[target]
    for command in COMMANDS.values():
        if target in command.aliases:
            return command
    return None


def execute_command(
    name: str, context: CommandContext, args: Sequence[str]
) -> CommandResponse | None:
    command = find_command(name)
    if command is None:
        return None
    return command.handler(context, args)
