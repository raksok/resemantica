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

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_dashboard()

    def _refresh_dashboard(self) -> None:
        state = self._get_run_state()
        events = self._load_recent_run_events()

        run_info = self.query_one("#dashboard-run-info", Static)
        if state:
            run_info.update(
                f"Status: {self._format_status_label(state, events)}\n"
                f"Stage:  {state['stage_name']}\n"
                f"Started: {state['started_at']}\n"
                f"Last event: {self._format_activity_age(state, events)}"
            )
        else:
            run_info.update("No active run.")

        phase = self.query_one("#dashboard-phase-progress", Static)
        phase_progress = self._build_phase_progress(state)
        phase.update(phase_progress)

        warnings_text = self.query_one("#dashboard-recent-warnings", Static)
        warnings_text.update(self._build_recent_warnings())

        stats = self.query_one("#dashboard-quick-stats", Static)
        stats.update(self._build_quick_stats(state=state, events=events))

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
        run_id = self._get_run_id()
        if not release_id or not run_id:
            return "[dim]No warnings.[/]"
        try:
            from resemantica.tracking.repo import ensure_tracking_db, load_events
            conn = ensure_tracking_db(release_id)
            try:
                events = load_events(conn, run_id=run_id, release_id=release_id, limit=5)
                if not events:
                    return "[dim]No warnings.[/]"
                lines = ["[bold]Recent Events[/bold]"]
                for ev in events[:5]:
                    sev_color = "orange" if ev.severity == "warning" else "red" if ev.severity == "error" else "comment"
                    lines.append(
                        f"  [{sev_color}]{ev.severity.upper():<7}[/] "
                        f"{self._format_event_summary(ev)}"
                    )
                return "\n".join(lines)
            finally:
                conn.close()
        except Exception:
            return "[dim]Could not load events.[/]"

    @staticmethod
    def _format_event_summary(event: Any) -> str:
        message = str(getattr(event, "message", "") or "").strip()
        event_type = str(getattr(event, "event_type", "") or "").strip()
        stage_name = str(getattr(event, "stage_name", "") or "").strip()
        parts = [message or event_type or "(event)"]

        chapter_number = getattr(event, "chapter_number", None)
        if chapter_number is not None:
            parts.append(f"ch={chapter_number}")

        block_id = getattr(event, "block_id", None)
        if block_id:
            parts.append(f"block={block_id}")

        payload = getattr(event, "payload", None)
        if isinstance(payload, dict):
            reason = payload.get("reason")
            if isinstance(reason, str) and reason:
                parts.append(f"reason={reason}")

        if stage_name and stage_name not in parts[0]:
            parts.append(f"stage={stage_name}")
        return "  ".join(parts)[:100]

    def _build_quick_stats(
        self,
        *,
        state: dict[str, Any] | None = None,
        events: list[Any] | None = None,
    ) -> str:
        state = self._get_run_state() if state is None else state
        if state is None:
            return "[dim]Quick stats unavailable without an active run.[/]"

        events = self._load_recent_run_events() if events is None else events
        return self._build_quick_stats_from_events(events)

    @staticmethod
    def _build_quick_stats_from_events(events: list[Any]) -> str:
        glossary_terms = sum(
            1
            for event in events
            if event.event_type == "preprocess-glossary.discover.term_found"
        )

        promoted_count = 0
        for event in events:
            if event.event_type != "preprocess-idioms.completed":
                continue
            payload = event.payload if isinstance(event.payload, dict) else {}
            raw_count = payload.get("promoted_count")
            if isinstance(raw_count, int):
                promoted_count = raw_count
                break

        extracted_entities = sum(
            1
            for event in events
            if event.event_type == "preprocess-graph.entity_extracted"
        )
        retry_total = sum(1 for event in events if "retry" in event.event_type.lower())

        risk_scores: list[float] = []
        for event in events:
            if "risk_detected" not in event.event_type.lower():
                continue
            payload = event.payload if isinstance(event.payload, dict) else {}
            score = payload.get("risk_score")
            if isinstance(score, (int, float)):
                risk_scores.append(float(score))

        has_relevant_events = any(
            [
                glossary_terms,
                promoted_count,
                extracted_entities,
                retry_total,
                bool(risk_scores),
            ]
        )
        if not has_relevant_events:
            return "[dim]Quick stats unavailable for this run yet.[/]"

        average_risk = sum(risk_scores) / len(risk_scores) if risk_scores else None
        avg_risk_text = f"{average_risk:.2f}" if average_risk is not None else "--"
        return "\n".join(
            [
                "[bold]Quick Stats[/bold]",
                f"  Glossary     {glossary_terms} terms",
                f"  Idioms       {promoted_count} policies",
                f"  Entities     {extracted_entities} extracted",
                f"  Retries      {retry_total} total",
                f"  Avg risk     {avg_risk_text}",
            ]
        )
