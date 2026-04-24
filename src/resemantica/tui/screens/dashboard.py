from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from resemantica.tui.screens.base import BaseScreen


class DashboardScreen(BaseScreen):
    def _content_widgets(self) -> ComposeResult:
        with Container(id="dashboard-content"):
            yield Static("Resemantica — Run Overview", classes="app-title")
            yield Static("", id="dashboard-run-info")
            yield Static("", id="dashboard-phase-progress")
            yield Static("", id="dashboard-recent-warnings")
            yield Static("", id="dashboard-quick-stats")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_dashboard()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_dashboard()

    def _refresh_dashboard(self) -> None:
        state = self._get_run_state()

        run_info = self.query_one("#dashboard-run-info", Static)
        if state:
            run_info.update(
                f"Status: [bold]{state['status'].upper()}[/bold]\n"
                f"Stage:  {state['stage_name']}\n"
                f"Started: {state['started_at']}"
            )
        else:
            run_info.update("No active run.")

        phase = self.query_one("#dashboard-phase-progress", Static)
        phase_progress = self._build_phase_progress(state)
        phase.update(phase_progress)

        warnings_text = self.query_one("#dashboard-recent-warnings", Static)
        warnings_text.update(self._build_recent_warnings())

        stats = self.query_one("#dashboard-quick-stats", Static)
        stats.update(self._build_quick_stats())

    def _build_phase_progress(self, state: dict[str, Any] | None) -> str:
        lines = ["[bold]Phase Progress[/bold]"]
        stages = [
            "preprocess-glossary",
            "preprocess-summaries",
            "preprocess-idioms",
            "preprocess-graph",
            "packets-build",
            "translate-chapter",
            "translate-pass3",
            "epub-rebuild",
        ]
        current_stage = state["stage_name"] if state else None
        for s in stages:
            done = False
            if current_stage:
                idx_now = stages.index(current_stage) if current_stage in stages else -1
                idx_s = stages.index(s)
                if idx_s < idx_now:
                    done = True
            marker = "■" if done else "▸" if s == current_stage else "□"
            color = "green" if done else "cyan" if s == current_stage else "comment"
            lines.append(f"  [{color}]{marker}[/] {s}")
        return "\n".join(lines)

    def _build_recent_warnings(self) -> str:
        release_id = self._get_release_id()
        if not release_id:
            return "[dim]No warnings.[/]"
        try:
            from resemantica.tracking.repo import ensure_tracking_db, load_events
            conn = ensure_tracking_db(release_id)
            try:
                events = load_events(conn, limit=5)
                if not events:
                    return "[dim]No warnings.[/]"
                lines = ["[bold]Recent Events[/bold]"]
                for ev in events[:5]:
                    sev_color = "orange" if ev.severity == "warning" else "red" if ev.severity == "error" else "comment"
                    lines.append(f"  [{sev_color}]{ev.severity.upper()}[/] {ev.message[:60]}")
                return "\n".join(lines)
            finally:
                conn.close()
        except Exception:
            return "[dim]Could not load events.[/]"

    def _build_quick_stats(self) -> str:
        return "[dim]Quick stats: connect to a run to see data.[/]"
