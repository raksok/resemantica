from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from resemantica.tui.screens.base import BaseScreen


class SettingsScreen(BaseScreen):
    def _content_widgets(self) -> ComposeResult:
        with Container(id="settings-content"):
            yield Static("Configuration", classes="app-title")
            yield Static("", id="settings-config-display")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_settings()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_settings()

    def _refresh_settings(self) -> None:
        config_display = self.query_one("#settings-config-display", Static)
        config_display.update(self._build_config_text())

    def _build_config_text(self) -> str:
        try:
            from resemantica.settings import load_config
            config = load_config()
            lines: list[str] = []

            lines.append("[bold]Models[/bold]")
            lines.append(f"  translator:  {config.models.translator_name}")
            lines.append(f"  analyst:     {config.models.analyst_name}")
            lines.append(f"  embedding:   {config.models.embedding_name}")

            lines.append("")
            lines.append("[bold]LLM[/bold]")
            lines.append(f"  base_url:    {config.llm.base_url}")
            lines.append(f"  timeout:     {config.llm.timeout_seconds}s")
            lines.append(f"  max_retries: {config.llm.max_retries}")
            lines.append(f"  context_win: {config.llm.context_window}")

            lines.append("")
            lines.append("[bold]Paths[/bold]")
            lines.append(f"  artifact_root: {config.paths.artifact_root}")
            lines.append(f"  db_filename:   {config.paths.db_filename}")

            lines.append("")
            lines.append("[bold]Budget[/bold]")
            lines.append(f"  max_context_per_pass: {config.budget.max_context_per_pass}")
            lines.append(f"  max_paragraph_chars:  {config.budget.max_paragraph_chars}")
            lines.append(f"  max_bundle_bytes:     {config.budget.max_bundle_bytes}")

            lines.append("")
            lines.append("[bold]Translation[/bold]")
            lines.append(f"  pass3_default:       {config.translation.pass3_default}")
            lines.append(f"  risk_threshold_high: {config.translation.risk_threshold_high}")

            return "\n".join(lines)
        except Exception as exc:
            return f"[red]Could not load config: {exc}[/]"
