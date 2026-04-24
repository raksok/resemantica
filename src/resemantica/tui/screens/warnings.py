from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Static

from resemantica.tui.screens.base import BaseScreen


class WarningsScreen(BaseScreen):
    def _content_widgets(self) -> ComposeResult:
        with Container(id="warnings-content"):
            yield Static("Warnings & Failures", classes="app-title")
            yield DataTable(id="warnings-table")

    def on_mount(self) -> None:
        super().on_mount()
        table = self.query_one("#warnings-table", DataTable)
        table.add_columns("Severity", "Event", "Message")
        self._refresh_warnings()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_warnings()

    def _refresh_warnings(self) -> None:
        table = self.query_one("#warnings-table", DataTable)
        table.clear()

        release_id = self._get_release_id()
        if not release_id:
            table.add_row("--", "--", "No release selected")
            return

        try:
            from resemantica.tracking.repo import ensure_tracking_db, load_events
            conn = ensure_tracking_db(release_id)
            try:
                events = load_events(conn, limit=50)
            finally:
                conn.close()
        except Exception:
            table.add_row("--", "--", "Could not load events")
            return

        for ev in events:
            table.add_row(
                ev.severity.upper(),
                ev.event_type,
                ev.message[:60],
            )
