from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static


class BaseScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static(id="pulse-bar"),
            Static(id="header-run-info"),
            Static(id="header-chapter-progress"),
            Static(id="header-pass"),
            id="header-container",
            classes="header-bar",
        )
        yield Vertical(id="spine-container", classes="spine")
        with Container(id="main-content"):
            yield from self._content_widgets()
        yield Horizontal(
            Static(id="footer-block-progress"),
            Static(id="footer-warnings"),
            Static(id="footer-failures"),
            Static(id="footer-elapsed"),
            Static(id="footer-keys"),
            id="footer-container",
            classes="footer-bar",
        )

    def _content_widgets(self) -> ComposeResult:
        yield Static("")

    def on_mount(self) -> None:
        self._update_header()
        self._update_spine()
        self._update_footer()
        self.set_interval(3, self._refresh_all)

    def _refresh_all(self) -> None:
        self._update_header()
        self._update_spine()
        self._update_footer()

    def _get_release_id(self) -> str | None:
        app = self.app
        return getattr(app, "release_id", None)

    def _get_run_id(self) -> str | None:
        app = self.app
        return getattr(app, "run_id", None)

    def _update_header(self) -> None:
        pulse = self.query_one("#pulse-bar", Static)
        pulse.update("▁▂▃▅▇█▇▅▃▂▁")

        run_id = self._get_run_id() or "--"
        release_id = self._get_release_id() or "--"
        run_info = self.query_one("#header-run-info", Static)
        run_info.update(f"Run: {run_id}  Rel: {release_id}")

    def _update_spine(self) -> None:
        spine = self.query_one("#spine-container", Vertical)
        spine.remove_children()

        title = Static("Chapter Spine", id="spine-title")
        spine.mount(title)

        for i in range(1, 21):
            label = f"□ Ch {i}"
            item = Static(label, classes="spine-item spine-status-not-started")
            spine.mount(item)

    def _update_footer(self) -> None:
        footer_keys = self.query_one("#footer-keys", Static)
        footer_keys.update("[1-7] Screen  [q] Quit")

    def _get_run_state(self) -> dict[str, Any] | None:
        run_id = self._get_run_id()
        release_id = self._get_release_id()
        if not run_id or not release_id:
            return None
        try:
            from resemantica.tracking.repo import ensure_tracking_db, load_run_state
            conn = ensure_tracking_db(release_id)
            try:
                state = load_run_state(conn, run_id)
                if state is None:
                    return None
                return {
                    "run_id": state.run_id,
                    "release_id": state.release_id,
                    "stage_name": state.stage_name,
                    "status": state.status,
                    "started_at": state.started_at,
                    "finished_at": state.finished_at,
                    "checkpoint": state.checkpoint,
                    "metadata": state.metadata,
                }
            finally:
                conn.close()
        except Exception:
            return None
