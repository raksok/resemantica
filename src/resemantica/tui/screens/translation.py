from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from resemantica.tui.screens.base import BaseScreen


class TranslationScreen(BaseScreen):
    def _content_widgets(self) -> ComposeResult:
        with Container(id="translation-content"):
            yield Static("Translation Progress", classes="app-title")
            yield Static("", id="translation-header")
            yield Static("", id="translation-block-list")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_translation()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_translation()

    def _refresh_translation(self) -> None:
        header = self.query_one("#translation-header", Static)
        state = self._get_run_state()
        if state:
            header.update(
                f"[bold]Stage:[/] {state['stage_name']}\n"
                f"[bold]Status:[/] {state['status']}"
            )
        else:
            header.update("[dim]No translation run active.[/]")

        block_list = self.query_one("#translation-block-list", Static)
        block_list.update(
            "[dim]Block-level translation progress will appear here\n"
            "when a translation run is active.[/]"
        )
