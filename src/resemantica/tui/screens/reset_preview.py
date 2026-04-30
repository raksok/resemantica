from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Static

from resemantica.tui.adapter import TUIAdapter
from resemantica.tui.screens.base import BaseScreen


class ResetPreviewScreen(BaseScreen):
    def _content_widgets(self) -> ComposeResult:
        with Container(id="reset-preview-content"):
            yield Static("Reset / Cleanup Preview", classes="app-title")
            yield Static("Scope: run", id="reset-scope")
            yield Static("", id="reset-preview")
            with Horizontal(id="reset-buttons"):
                yield Button("Preview", id="btn-reset-preview", variant="default")
                yield Button("Apply", id="btn-reset-apply", variant="warning", disabled=True)

    def on_mount(self) -> None:
        super().on_mount()
        self._scope = "run"
        self._has_preview = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-reset-preview":
            self._preview()
        if event.button.id == "btn-reset-apply":
            self._apply()

    def _adapter(self) -> TUIAdapter | None:
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if not release_id or not run_id:
            return None
        return TUIAdapter(release_id=release_id, run_id=run_id, config_path=getattr(self.app, "config_path", None))

    def _preview(self) -> None:
        target = self.query_one("#reset-preview", Static)
        adapter = self._adapter()
        if adapter is None:
            target.update("[red]Need release_id and run_id to preview cleanup.[/]")
            return
        plan = adapter.preview_reset(self._scope)
        target.update(self._render_plan(plan))
        self._has_preview = True
        self.query_one("#btn-reset-apply", Button).disabled = False

    def _apply(self) -> None:
        target = self.query_one("#reset-preview", Static)
        if not self._has_preview:
            target.update("[red]Preview cleanup before applying.[/]")
            return
        adapter = self._adapter()
        if adapter is None:
            return
        report = adapter.apply_reset(self._scope)
        target.update(
            f"Deleted files: {len(report.get('deleted_files', []))}\n"
            f"Deleted directories: {len(report.get('deleted_dirs', []))}\n"
            f"SQLite rows deleted: {report.get('sqlite_rows_deleted', 0)}"
        )
        self.query_one("#btn-reset-apply", Button).disabled = True

    def _render_plan(self, plan: dict[str, object]) -> str:
        deletable = list(plan.get("deletable_artifacts", []))
        preserved = list(plan.get("preserved_artifacts", []))
        lines = [f"WILL DELETE ({len(deletable)} items)"]
        lines.extend(f"  {item}" for item in deletable[:10])
        lines.append("")
        lines.append(f"WILL PRESERVE ({len(preserved)} items)")
        lines.extend(f"  {item}" for item in preserved[:10])
        return "\n".join(lines)
