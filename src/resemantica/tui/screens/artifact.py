from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Static, Tree

from resemantica.tui.screens.base import BaseScreen


class ArtifactScreen(BaseScreen):
    BINDINGS = [
        Binding("y", "cleanup_preview", "Dry Run"),
        Binding("a", "cleanup_apply", "Apply"),
    ]

    def on_mount(self) -> None:
        super().on_mount()
        self._scope: str = "run"
        self._preview_done: bool = False
        self._show_hints()

    def _show_hints(self) -> None:
        preview = self.query_one("#artifact-cleanup-preview", Static)
        preview.update("[dim]y[/]=Dry Run  [dim]a[/]=Apply  (preview first)")

    def _content_widgets(self) -> ComposeResult:
        with Container(id="artifact-content"):
            with Vertical(id="artifact-tree-section"):
                yield Static("Artifacts", classes="app-title")
                yield Tree("artifacts", id="artifact-tree")
            with Vertical(id="artifact-cleanup-section"):
                yield Static("Cleanup", id="artifact-cleanup-title", classes="section-title")
                yield Static("Scope: run", id="artifact-cleanup-scope-info")
                yield Static("", id="artifact-cleanup-preview")

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_artifacts()

    def _refresh_artifacts(self) -> None:
        tree = self.query_one("#artifact-tree", Tree)
        tree.clear()

        release_id = self._get_release_id()
        if not release_id:
            return

        try:
            from resemantica.settings import load_config
            cfg = load_config()
            artifact_root = Path(cfg.paths.artifact_root)
            release_root = artifact_root / "releases" / release_id
            if not release_root.exists():
                tree.root.add("[dim]No artifacts directory found[/]")
                return
            self._populate_tree(tree.root, release_root, max_depth=4)
        except Exception:
            tree.root.add("[dim]Could not load artifacts[/]")

    def _populate_tree(self, node: Any, directory: Path, max_depth: int = 3) -> None:
        if max_depth <= 0:
            return
        try:
            for child in sorted(directory.iterdir()):
                if child.is_dir():
                    sub = node.add(f"[bold]{child.name}/[/]")
                    self._populate_tree(sub, child, max_depth - 1)
                else:
                    size = child.stat().st_size
                    node.add(f"{child.name} ({size}B)")
        except PermissionError:
            node.add("[dim](access denied)[/]")

    def _update_preview(self, text: str) -> None:
        target = self.query_one("#artifact-cleanup-preview", Static)
        lines = text.split("\n")
        lines.append("")
        lines.append("[dim]y[/]=Dry Run  [dim]a[/]=Apply")
        target.update("\n".join(lines))

    def action_cleanup_preview(self) -> None:
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if not release_id or not run_id:
            self._update_preview("[red]Need release_id and run_id to plan cleanup.[/]")
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
            self._update_preview("\n".join(lines))
            self._preview_done = True
        except Exception as exc:
            self._update_preview(f"[red]Error: {exc}[/]")

    def action_cleanup_apply(self) -> None:
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if not release_id or not run_id:
            return

        if not self._preview_done:
            preview = self.query_one("#artifact-cleanup-preview", Static)
            preview.update("[red]Preview cleanup before applying.[/]")
            return

        try:
            from resemantica.orchestration.cleanup import apply_cleanup
            result = apply_cleanup(release_id, run_id, scope=self._scope)
            lines: list[str] = []
            lines.append(f"[bold]Cleanup {'succeeded' if result.get('success', True) else 'failed'}[/]")
            lines.append(f"  Files deleted: {len(result.get('deleted_files', []))}")
            lines.append(f"  Directories deleted: {len(result.get('deleted_dirs', []))}")
            lines.append(f"  SQLite rows deleted: {result.get('sqlite_rows_deleted', 0)}")
            if result.get("errors"):
                lines.append("[red]Errors:[/]")
                for e in result["errors"]:
                    lines.append(f"  [red]{e}[/]")
            self._update_preview("\n".join(lines))
            self._preview_done = False
        except Exception as exc:
            self._update_preview(f"[red]Error: {exc}[/]")
