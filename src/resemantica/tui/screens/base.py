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
        try:
            app = self.app
        except Exception:
            return None
        return getattr(app, "release_id", None)

    def _get_run_id(self) -> str | None:
        try:
            app = self.app
        except Exception:
            return None
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

        chapter_data = self._get_chapter_spine_data()
        if chapter_data:
            for label, css in self._render_spine_items(chapter_data):
                spine.mount(Static(label, classes=css))
        else:
            spine.mount(Static("[dim]No chapter data.[/]", classes="spine-item"))

    def _get_chapter_spine_data(self) -> list[tuple[int, str]]:
        release_id = self._get_release_id()
        if not release_id:
            return []
        try:
            from resemantica.settings import derive_paths, load_config
            from resemantica.chapters.manifest import list_extracted_chapters

            config = load_config(getattr(self.app, "config_path", None))
            paths = derive_paths(config, release_id=release_id)
            refs = list_extracted_chapters(paths)
            chapter_numbers = [ref.chapter_number for ref in refs]

            run_id = self._get_run_id()
            if run_id:
                statuses = self._load_chapter_statuses(release_id, run_id)
                return [(n, statuses.get(n, "not-started")) for n in chapter_numbers]
            return [(n, "not-started") for n in chapter_numbers]
        except Exception:
            return []

    def _load_chapter_statuses(self, release_id: str, run_id: str) -> dict[int, str]:
        from resemantica.tracking.repo import ensure_tracking_db, load_events

        conn = ensure_tracking_db(release_id)
        try:
            events = load_events(conn, run_id=run_id, release_id=release_id, limit=1000)
            statuses: dict[int, str] = {}
            for ev in reversed(events):
                if ev.chapter_number is None:
                    continue
                if ev.event_type == "chapter_completed":
                    statuses[ev.chapter_number] = "complete"
                elif ev.event_type == "chapter_started" and ev.chapter_number not in statuses:
                    statuses[ev.chapter_number] = "in-progress"
                elif "fail" in (ev.event_type or "").lower() and ev.chapter_number not in statuses:
                    statuses[ev.chapter_number] = "failed"
            return statuses
        finally:
            conn.close()

    @staticmethod
    def _render_spine_items(chapter_data: list[tuple[int, str]]) -> list[tuple[str, str]]:
        STATUS_MAP: dict[str, tuple[str, str]] = {
            "not-started": ("□", "spine-status-not-started"),
            "in-progress": ("▸", "spine-status-in-progress"),
            "complete": ("■", "spine-status-complete"),
            "failed": ("✗", "spine-status-failed"),
            "high-risk": ("◈", "spine-status-high-risk"),
        }
        items: list[tuple[str, str]] = []
        for ch_num, status in chapter_data:
            char, css = STATUS_MAP.get(status, STATUS_MAP["not-started"])
            items.append((f"{char} Ch {ch_num}", f"spine-item {css}"))
        return items

    def _update_footer(self) -> None:
        footer_keys = self.query_one("#footer-keys", Static)
        footer_keys.update("[1-9] Screen  [q] Quit")

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

    def _make_adapter(self):
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if not release_id or not run_id:
            return None
        from resemantica.tui.adapter import TUIAdapter

        return TUIAdapter(
            release_id=release_id,
            run_id=run_id,
            config_path=getattr(self.app, "config_path", None),
        )
