from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence, TYPE_CHECKING

import yfinance as yf
from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import App

from tradr.market import get_ohlcv
from tradr import groq
from tradr import trading
from tradr.widgets.chart import Chart
from tradr.widgets.watchlist import Watchlist

if TYPE_CHECKING:
    from tradr.widgets.ai import AiChat


@dataclass(slots=True)
class CommandResponse:
    """Normalized response from a command handler."""

    message: Any
    success: bool = True
    history_text: str | None = None

    @classmethod
    def ok(cls, message: Any, history_text: str | None = None) -> "CommandResponse":
        return cls(message=message, success=True, history_text=history_text)

    @classmethod
    def error(cls, message: str) -> "CommandResponse":
        return cls(message=f"[red]{message}[/red]", success=False, history_text=message)


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
    run_in_background: bool = False


def _format_decimal(value: Any, fallback: str = "n/a") -> str:
    if value in (None, ""):
        return fallback
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _account_table(account: dict[str, Any]) -> Table:
    table = Table(title="Paper Account")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="bold")
    rows = [
        ("Status", account.get("status", "unknown")),
        ("Buying Power", _format_decimal(account.get("buying_power"))),
        ("Equity", _format_decimal(account.get("equity"))),
        ("Cash", _format_decimal(account.get("cash"))),
        ("Portfolio Value", _format_decimal(account.get("portfolio_value"))),
    ]
    for label, value in rows:
        table.add_row(label, str(value))
    return table


def _positions_table(positions: Sequence[dict[str, Any]]) -> Table:
    table = Table(title="Open Positions")
    table.add_column("Symbol", style="cyan")
    table.add_column("Qty", justify="right")
    table.add_column("Market Value", justify="right")
    table.add_column("Unrealized P/L", justify="right")
    for position in positions:
        table.add_row(
            str(position.get("symbol", "n/a")),
            str(position.get("qty", "n/a")),
            _format_decimal(position.get("market_value")),
            _format_decimal(position.get("unrealized_pl")),
        )
    return table


def _orders_table(orders: Sequence[dict[str, Any]]) -> Table:
    table = Table(title="Recent Orders")
    table.add_column("Ref", style="cyan bold")
    table.add_column("Submitted", style="dim")
    table.add_column("Symbol", style="cyan")
    table.add_column("Side")
    table.add_column("Qty", justify="right")
    table.add_column("Type")
    table.add_column("Status")
    for order in orders:
        table.add_row(
            str(order.get("ref", "")),
            str(order.get("submitted_at", "n/a")),
            str(order.get("symbol", "n/a")),
            str(order.get("side", "n/a")),
            str(order.get("qty", "n/a")),
            str(order.get("order_type", "n/a")),
            str(order.get("status", "n/a")),
        )
    return table


def _commands_table(commands: Sequence["Command"]) -> Table:
    table = Table(title="Available Commands")
    table.add_column("Command", style="cyan bold")
    table.add_column("Usage", style="dim")
    table.add_column("Description")
    for command in commands:
        alias_note = f" [{', '.join(command.aliases)}]" if command.aliases else ""
        table.add_row(
            f"{command.name}{alias_note}",
            command.usage,
            command.description,
        )
    return table


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
    return CommandResponse.ok(
        _commands_table(list(COMMANDS.values())),
        history_text="Listed available commands.",
    )


def _submit_order(symbol: str, qty: float, side: str) -> CommandResponse:
    try:
        order = trading.place_order({"symbol": symbol, "qty": qty, "side": side})
    except FileNotFoundError as exc:
        return CommandResponse.error(str(exc))
    except ValueError as exc:
        return CommandResponse.error(str(exc))
    except Exception as exc:
        return CommandResponse.error(f"Failed to submit {side} order: {exc}")
    ref = trading.remember_order(order)
    status = order.get("status", "accepted")
    order_id = order.get("id", "n/a")
    ref_text = f" · ref=[cyan]{ref}[/cyan]" if ref else ""
    history_ref_text = f" · ref={ref}" if ref else ""
    return CommandResponse.ok(
        f"Submitted paper {side} order for [bold]{qty:g}[/bold] shares of "
        f"[bold]{symbol}[/bold]. Status: [green]{status}[/green]{ref_text} · id={order_id}",
        history_text=f"Submitted paper {side} order for {qty:g} shares of {symbol}. "
        f"Status: {status}{history_ref_text} · id={order_id}",
    )


def buy_stock(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    if len(args) < 2:
        return CommandResponse.error("Usage: buy <symbol> <qty>")
    symbol = args[0].upper()
    try:
        qty = float(args[1])
    except ValueError:
        return CommandResponse.error("Quantity must be numeric.")
    if qty <= 0:
        return CommandResponse.error("Quantity must be greater than zero.")
    return _submit_order(symbol, qty, "buy")


def sell_stock(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    if len(args) < 2:
        return CommandResponse.error("Usage: sell <symbol> <qty>")
    symbol = args[0].upper()
    try:
        qty = float(args[1])
    except ValueError:
        return CommandResponse.error("Quantity must be numeric.")
    if qty <= 0:
        return CommandResponse.error("Quantity must be greater than zero.")
    return _submit_order(symbol, qty, "sell")


def close_position(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    if not args:
        return CommandResponse.error("Usage: close <symbol>")
    symbol = args[0].upper()
    try:
        result = trading.close_position(symbol)
        status = result.get("status", "accepted")
        return CommandResponse.ok(
            f"Submitted close request for [bold]{symbol}[/bold]. "
            f"Status: [green]{status}[/green]",
            history_text=f"Submitted close request for {symbol}. Status: {status}",
        )
    except ValueError as exc:
        return CommandResponse.error(str(exc))
    except Exception as exc:
        return CommandResponse.error(f"Failed to close position: {exc}")


def cancel_order(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    if not args:
        return CommandResponse.error("Usage: cancel-order <order_id|#ref>")
    order_id = args[0].strip()
    try:
        trading.cancel_order(order_id)
        return CommandResponse.ok(
            f"Submitted cancel request for order [bold]{order_id}[/bold].",
            history_text=f"Submitted cancel request for order {order_id}.",
        )
    except ValueError as exc:
        return CommandResponse.error(str(exc))
    except Exception as exc:
        return CommandResponse.error(f"Failed to cancel order: {exc}")


def cancel_last_order(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    last_order = trading.get_last_order_reference()
    if last_order is None:
        return CommandResponse.error("No recent order is available to cancel.")
    ref = last_order["ref"]
    try:
        trading.cancel_order(ref)
        return CommandResponse.ok(
            f"Submitted cancel request for last order [bold]{ref}[/bold].",
            history_text=f"Submitted cancel request for last order {ref}.",
        )
    except ValueError as exc:
        return CommandResponse.error(str(exc))
    except Exception as exc:
        return CommandResponse.error(f"Failed to cancel last order: {exc}")


def set_paper_trading_keys(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    if len(args) < 2:
        return CommandResponse.error("Usage: set-paper <ALPACA_API_KEY> <ALPACA_SECRET_KEY>")
    config = {
        "api_key": args[0].strip(),
        "secret_key": args[1].strip(),
        "paper": True,
    }
    try:
        trading.save_trading_config(config)
        trading.init_trading_client(config)
        return CommandResponse.ok(
            "Alpaca paper-trading credentials saved and validated.",
            history_text="Alpaca paper-trading credentials saved and validated.",
        )
    except ValueError as exc:
        return CommandResponse.error(str(exc))
    except Exception as exc:
        return CommandResponse.error(f"Failed to save trading credentials: {exc}")


def show_account(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    try:
        account = trading.get_account()
    except FileNotFoundError as exc:
        return CommandResponse.error(str(exc))
    except Exception as exc:
        return CommandResponse.error(f"Failed to load account: {exc}")

    return CommandResponse.ok(
        _account_table(account),
        history_text="Loaded paper account summary.",
    )


def show_positions(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    try:
        positions = trading.get_positions()
    except FileNotFoundError as exc:
        return CommandResponse.error(str(exc))
    except Exception as exc:
        return CommandResponse.error(f"Failed to load positions: {exc}")

    if not positions:
        return CommandResponse.ok("No open paper positions.")

    return CommandResponse.ok(
        _positions_table(positions),
        history_text=f"Loaded {len(positions)} open positions.",
    )


def show_portfolio(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    try:
        account = trading.get_account()
        positions = trading.get_positions()
    except FileNotFoundError as exc:
        return CommandResponse.error(str(exc))
    except Exception as exc:
        return CommandResponse.error(f"Failed to load portfolio: {exc}")

    renderables: list[Any] = [_account_table(account)]
    if positions:
        renderables.append(_positions_table(positions))
        history_text = f"Loaded portfolio with {len(positions)} positions."
    else:
        renderables.append(Text("No open paper positions.", style="dim"))
        history_text = "Loaded portfolio with no open positions."
    return CommandResponse.ok(Group(*renderables), history_text=history_text)


def show_orders(context: CommandContext, args: Sequence[str]) -> CommandResponse:
    limit = 20
    if args:
        try:
            limit = int(args[0])
        except ValueError:
            return CommandResponse.error("Usage: orders [limit]")
        if limit <= 0:
            return CommandResponse.error("Order limit must be greater than zero.")

    try:
        orders = trading.get_orders(limit=limit)
    except FileNotFoundError as exc:
        return CommandResponse.error(str(exc))
    except Exception as exc:
        return CommandResponse.error(f"Failed to load orders: {exc}")

    if not orders:
        return CommandResponse.ok("No recent paper orders.")
    return CommandResponse.ok(
        _orders_table(orders),
        history_text=f"Loaded {len(orders)} recent paper orders.",
    )


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
        description="Submit a paper buy order",
        usage="buy <symbol> <qty>",
        handler=buy_stock,
        run_in_background=True,
    ),
    "sell": Command(
        name="sell",
        description="Submit a paper sell order",
        usage="sell <symbol> <qty>",
        handler=sell_stock,
        run_in_background=True,
    ),
    "close": Command(
        name="close",
        description="Close an open paper position",
        usage="close <symbol>",
        handler=close_position,
        run_in_background=True,
    ),
    "cancel-order": Command(
        name="cancel-order",
        description="Cancel a paper order by ID",
        usage="cancel-order <order_id|#ref>",
        handler=cancel_order,
        aliases=("cancel",),
        run_in_background=True,
    ),
    "cancel-last": Command(
        name="cancel-last",
        description="Cancel the most recent tracked paper order",
        usage="cancel-last",
        handler=cancel_last_order,
        run_in_background=True,
    ),
    "set-paper": Command(
        name="set-paper",
        description="Validate and store Alpaca paper-trading credentials",
        usage="set-paper <ALPACA_API_KEY> <ALPACA_SECRET_KEY>",
        handler=set_paper_trading_keys,
        run_in_background=True,
    ),
    "set-key": Command(
        name="set-key",
        description="Validate and store Groq API key",
        usage="set-key <GROQ_API_KEY>",
        handler=set_api_key,
    ),
    "account": Command(
        name="account",
        description="Show paper account summary",
        usage="account",
        handler=show_account,
        run_in_background=True,
    ),
    "positions": Command(
        name="positions",
        description="Show open paper positions",
        usage="positions",
        handler=show_positions,
        run_in_background=True,
    ),
    "portfolio": Command(
        name="portfolio",
        description="Show account summary and open positions",
        usage="portfolio",
        handler=show_portfolio,
        run_in_background=True,
    ),
    "orders": Command(
        name="orders",
        description="Show recent paper orders",
        usage="orders [limit]",
        handler=show_orders,
        run_in_background=True,
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
