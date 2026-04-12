from __future__ import annotations

import os
import re
from rich.markdown import Markdown
from rich.text import Text
from textual.containers import Vertical
from textual.widgets import Input, RichLog
from textual.app import ComposeResult
from textual.widget import Widget
from textual import on, work

from tradr.commands import CommandContext, CommandResponse, execute_command
from tradr import groq


class AiChat(Widget):
    """AI + Command Terminal"""
    can_focus = True

    def __init__(self) -> None:
        super().__init__(id="terminal")
        self.history: list[tuple[str, str]] = []
        self.ai_ready: bool = False

    def compose(self) -> ComposeResult:
        self.output = RichLog(id="output", highlight=True, markup=True)
        self.input = Input(placeholder="Chat/Type commands here", id="input", compact=True)

        yield self.output
        yield self.input

    def on_mount(self) -> None:
        self.query_one("#input", Input).focus()
        self._init_ai_client()

    def _init_ai_client(self) -> None:
        try:
            api_key = os.getenv("GROQ_API_KEY")
            if api_key:
                groq.init_client(api_key)
                self.ai_ready = True
                return

            key = groq.get_api_key()
            groq.init_client(key)
            self.ai_ready = True
        except FileNotFoundError:
            self.ai_ready = False
            self.output.write(
                "[yellow]Set GROQ_API_KEY or run set-key <GROQ_API_KEY> to enable AI responses.[/yellow]"
            )
        except ValueError as exc:
            self.ai_ready = False
            self.output.write(f"[red]Failed to initialize Groq client: {exc}[/red]")
        except Exception as exc:
            self.ai_ready = False
            self.output.write(f"[red]Could not connect to Groq: {exc}[/red]")

    def clear_history(self, clear_log: bool = False) -> None:
        """Clear stored chat history and optionally wipe the log."""
        self.history.clear()
        if clear_log:
            self.output.clear()

    # COMMAND HANDLER
    def run_command(self, text: str) -> bool:
        parts = text.strip().split()

        if not parts:
            return True

        cmd = parts[0].lower()
        args = parts[1:]
        context = CommandContext(app=self.app, chat=self)

        response = execute_command(cmd, context, args)
        if response is None:
            return False

        self._write_response(response)
        if response.success:
            plain = Text.from_markup(response.message).plain
            self._record_history("assistant", plain)
        return True

    def _write_response(self, response: CommandResponse) -> None:
        self.output.write(response.message)

    def _record_history(self, role: str, text: str) -> None:
        self.history.append((role, text.strip()))
        if len(self.history) > 50:
            self.history = self.history[-50:]

    def chat_with_ai(self, text: str):
        if not self.ai_ready:
            self.output.write(
                "[magenta]AI assistant unavailable. Set GROQ_API_KEY to enable it.[/magenta]"
            )
            return

        context = self._compose_context()
        prompt = groq.load_prompt(context=context, question=text)
        self.output.write("[magenta]AI:[/magenta] Thinking...")
        self._ask_ai(prompt)

    def _compose_context(self) -> str:
        lines: list[str] = []
        try:
            from tradr.widgets.chart import Chart

            chart = self.app.query_one("#chart", Chart)
            lines.append(
                f"Chart symbol: {chart.symbol}, period: {chart.period}, interval: {chart.interval}"
            )
        except Exception:
            pass

        try:
            from tradr.widgets.watchlist import Watchlist

            watchlist = self.app.query_one("#watchlist", Watchlist)
            if watchlist.pinned_symbols:
                pins = ", ".join(watchlist.pinned_symbols[:10])
                lines.append(f"Pinned symbols: {pins}")
        except Exception:
            pass

        lines.extend(f"{role.upper()}: {text}" for role, text in self.history[-10:])
        return "\n".join(lines)

    @work(thread=True)
    def _ask_ai(self, prompt: str) -> None:
        try:
            reply = groq.answer_question(prompt)
        except Exception as exc:
            self.app.call_from_thread(self._handle_ai_error, exc)
            return
        self.app.call_from_thread(self._handle_ai_reply, reply)

    def _handle_ai_reply(self, reply: str) -> None:
        if self._looks_like_markdown(reply):
            try:
                markdown = Markdown(reply)
                self.output.write(Text.from_markup("[magenta]AI:[/magenta]"))
                self.output.write(markdown)
                self._record_history("assistant", reply)
                return
            except Exception:
                pass

        self.output.write(f"[magenta]AI:[/magenta] {reply}")
        self._record_history("assistant", reply)

    def _handle_ai_error(self, error: Exception) -> None:
        self.output.write(f"[red]AI error: {error}[/red]")

    def _looks_like_markdown(self, text: str) -> bool:
        markdown_patterns = [
            r"\*\*.+\*\*",
            r"__.+__",
            r"`.+`",
            r"```.+```",
            r"^#+\s",
            r"\*\s.+",
        ]
        return any(re.search(pattern, text, flags=re.DOTALL | re.MULTILINE) for pattern in markdown_patterns)


    # INPUT HANDLER
    @on(Input.Submitted)
    def handle_input(self, event: Input.Submitted) -> None:
        text = event.value.strip()

        if not text:
            return

        self.output.write(f"[bold]>[/bold] {text}")
        self._record_history("user", text)

        handled = self.run_command(text)
        if not handled:
            self.chat_with_ai(text)

        # clear input
        event.input.value = ""
