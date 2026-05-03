from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Input, Static

from resemantica.tui.screens.base import BaseScreen


class SettingsScreen(BaseScreen):
    BINDINGS = [
        Binding("l", "load_config", "Load"),
    ]

    def _content_widgets(self) -> ComposeResult:
        with Container(id="settings-content"):
            yield Static("Configuration", classes="app-title")
            yield Input(placeholder="/path/to/config.toml", id="config-path-input")
            yield Static("", id="settings-active-config")
            yield Static("", id="settings-config-display")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_settings()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_settings()

    def _refresh_settings(self) -> None:
        active = self.query_one("#settings-active-config", Static)
        path = getattr(self.app, "config_path", None)
        active.update(f"Active: [bold]{path or '[dim]default[/]'}[/]")
        config_display = self.query_one("#settings-config-display", Static)
        config_display.update(self._build_config_text())

    def _build_config_text(self) -> str:
        try:
            from resemantica.settings import load_config
            try:
                app = self.app
            except Exception:
                app = None
            config = load_config(getattr(app, "config_path", None) if app else None)
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
            lines.append("[bold]Model Budgets[/bold]")
            lines.append(
                f"  translator ctx: {config.models.effective_context_window('translator', config.llm.context_window)}"
            )
            lines.append(
                f"  analyst ctx:    {config.models.effective_context_window('analyst', config.llm.context_window)}"
            )

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

    def action_load_config(self) -> None:
        path_str = self.query_one("#config-path-input", Input).value
        if not path_str.strip():
            self.notify("No path entered", severity="warning", timeout=3)
            return
        path = Path(path_str).expanduser().resolve()
        if not path.exists():
            self.notify(f"Config not found: {path}", severity="error", timeout=3)
            return
        if path.suffix != ".toml":
            self.notify("Config must be a .toml file", severity="error", timeout=3)
            return
        self.app._config_path = path
        self.notify(f"Config loaded: {path}", timeout=3)
        self._refresh_settings()
