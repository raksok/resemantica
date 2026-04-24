from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static, Tree

from resemantica.tui.screens.base import BaseScreen


class ArtifactsScreen(BaseScreen):
    def _content_widgets(self) -> ComposeResult:
        with Container(id="artifacts-content"):
            yield Static("Artifacts", classes="app-title")
            yield Tree("artifacts", id="artifacts-tree")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_artifacts()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_artifacts()

    def _refresh_artifacts(self) -> None:
        tree = self.query_one("#artifacts-tree", Tree)
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
                    sub = node.add(f"📁 {child.name}/")
                    self._populate_tree(sub, child, max_depth - 1)
                else:
                    size = child.stat().st_size
                    node.add(f"📄 {child.name} ({size}B)")
        except PermissionError:
            node.add("[dim](access denied)[/]")
