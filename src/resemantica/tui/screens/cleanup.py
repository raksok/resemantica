from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Static

from resemantica.tui.screens.base import BaseScreen


class CleanupScreen(BaseScreen):
    def _content_widgets(self) -> ComposeResult:
        with Container(id="cleanup-content"):
            yield Static("Cleanup Workflow", classes="app-title")
            yield Static(
                "Scope: run | [dim]translation[/] | [dim]preprocess[/] | [dim]cache[/] | [dim]all[/]",
                id="cleanup-scope-info",
            )
            yield Static("", id="cleanup-scope-selector")
            yield Static("", id="cleanup-preview")
            with Horizontal(id="cleanup-buttons"):
                yield Button("Dry Run", id="btn-dry-run", variant="default")
                yield Button("Apply", id="btn-apply", variant="warning", disabled=True)

    def on_mount(self) -> None:
        super().on_mount()
        self._scope: str = "run"
        self._preview_result: str = ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-dry-run":
            self._run_dry_run()
        elif event.button.id == "btn-apply":
            self._run_apply()

    def _run_dry_run(self) -> None:
        preview = self.query_one("#cleanup-preview", Static)
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if not release_id or not run_id:
            preview.update("[red]Need release_id and run_id to plan cleanup.[/]")
            return

        try:
            from resemantica.orchestration.cleanup import plan_cleanup
            plan = plan_cleanup(release_id, run_id, scope=self._scope, dry_run=True)
            lines: list[str] = []
            lines.append(f"[bold]WILL DELETE[/bold] ({len(plan['deletable_artifacts'])} items)")
            for a in plan["deletable_artifacts"][:10]:
                lines.append(f"  [orange]{a}[/]")
            if len(plan["deletable_artifacts"]) > 10:
                lines.append(f"  ... and {len(plan['deletable_artifacts']) - 10} more")
            lines.append("")
            lines.append(f"[bold]WILL PRESERVE[/bold] ({len(plan['preserved_artifacts'])} items)")
            for a in plan["preserved_artifacts"][:5]:
                lines.append(f"  [green]{a}[/]")
            preview.update("\n".join(lines))
            self._preview_result = plan["scope"]
            btn = self.query_one("#btn-apply", Button)
            btn.disabled = False
        except Exception as exc:
            preview.update(f"[red]Error: {exc}[/]")

    def _run_apply(self) -> None:
        preview = self.query_one("#cleanup-preview", Static)
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if not release_id or not run_id:
            return

        try:
            from resemantica.orchestration.cleanup import apply_cleanup
            result = apply_cleanup(release_id, run_id, scope=self._scope)
            lines: list[str] = []
            lines.append(f"[bold]Cleanup {result.get('success', True)}[/]")
            lines.append(f"  Files deleted: {len(result.get('deleted_files', []))}")
            lines.append(f"  Directories deleted: {len(result.get('deleted_dirs', []))}")
            lines.append(f"  SQLite rows deleted: {result.get('sqlite_rows_deleted', 0)}")
            if result.get("errors"):
                lines.append("[red]Errors:[/]")
                for e in result["errors"]:
                    lines.append(f"  [red]{e}[/]")
            preview.update("\n".join(lines))
            btn = self.query_one("#btn-apply", Button)
            btn.disabled = True
        except Exception as exc:
            preview.update(f"[red]Error: {exc}[/]")

    def _refresh_all(self) -> None:
        super()._refresh_all()
