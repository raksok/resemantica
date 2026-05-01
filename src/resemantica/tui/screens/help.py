from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from resemantica.tui.navigation import SCREEN_INFOS, ScreenInfo, format_location


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close_help", "Close", priority=True),
        Binding("?", "close_help", "Close", priority=True),
    ]

    def __init__(self, current_screen_info: ScreenInfo | None = None) -> None:
        super().__init__()
        self._current_screen_info = current_screen_info

    def compose(self) -> ComposeResult:
        with Container(id="help-dialog"):
            yield Static("Resemantica TUI Help", id="help-title")
            yield Static(self._build_help_text(), id="help-content")

    def action_close_help(self) -> None:
        self.app.pop_screen()

    def _build_help_text(self) -> str:
        lines = [
            f"[b]{format_location(self._current_screen_info)}[/]",
            "",
            "[b]Screens[/]",
        ]
        for info in SCREEN_INFOS:
            current = " *" if info == self._current_screen_info else ""
            lines.append(f"{info.number} {info.title:<13} {info.purpose}{current}")
        lines.extend(
            [
                "",
                "[b]Keys[/]",
                "1-7 Switch   ? Help   q Quit",
                "",
                "[b]Screen Keys[/]",
                "1: [[ NEW FILE ]]  [[ RESUME RUN ]]  p=Production  n=Next Stage",
                "2: e=Extract",
                "3: g=Glossary   s=Summaries   i=Idioms   r=Graph   b=Packets",
                "4: t=Translate   u=Rebuild",
                "5: v=Verbose   s=Source   e=Severity   f=Stage   c=Chapter   r=Refresh",
                "6: y=Dry Run   a=Apply",
            ]
        )
        return "\n".join(lines)
