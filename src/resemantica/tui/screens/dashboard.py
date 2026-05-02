from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Static

from resemantica.tui.launch_control import STAGE_DEFINITIONS
from resemantica.tui.screens.base import BaseScreen

STATUS_COLORS = {
    "missing": "comment",
    "ready": "green",
    "running": "cyan",
    "done": "green",
    "failed": "red",
    "blocked": "orange",
    "stale": "orange",
    "disabled": "dim",
}

STATUS_GLYPH = {
    "missing": "○",
    "ready": "◉",
    "running": "◉",
    "done": "●",
    "failed": "✗",
    "blocked": "⊘",
    "stale": "◉",
    "disabled": "○",
}


class DashboardScreen(BaseScreen):
    BINDINGS = [
        Binding("left", "focus_prev_action", "Previous"),
        Binding("right", "focus_next_action", "Next"),
    ]

    async def key_2(self) -> None:
        await self.app.action_switch_screen("ingestion")

    async def key_3(self) -> None:
        await self.app.action_switch_screen("preprocessing")

    async def key_4(self) -> None:
        await self.app.action_switch_screen("translation")

    async def key_5(self) -> None:
        await self.app.action_switch_screen("observability")

    async def key_6(self) -> None:
        await self.app.action_switch_screen("artifact")

    async def key_7(self) -> None:
        await self.app.action_switch_screen("settings")

    def _content_widgets(self) -> ComposeResult:
        with Container(id="dashboard-content"):
            with Horizontal(id="dashboard-main"):
                with Vertical(id="dashboard-left"):
                    yield Static("Dashboard", classes="app-title")
                    yield Static("", id="dashboard-session-info")
                    with Horizontal(id="dashboard-action-list"):
                        yield Button(Text("[[ NEW FILE ]]"), id="btn-new-file")
                        yield Button(Text("[[ RESUME RUN ]]"), id="btn-resume-run")
                    yield Static("", id="dashboard-stage-list")
                    yield Static("", id="dashboard-active-worker")
                    yield Static("", id="dashboard-latest-failure")
                with Vertical(id="dashboard-event-panel"):
                    yield Static("", id="dashboard-event-tail", classes="event-tail")

    def on_mount(self) -> None:
        super().on_mount()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_dashboard()

    def _refresh_live_progress(self) -> None:
        super()._refresh_live_progress()
        events = self._recent_events_for_refresh()
        
        # Update stage list in real-time
        self.query_one("#dashboard-stage-list", Static).update(self._render_stage_list())

        worker_widget = self.query_one("#dashboard-active-worker", Static)
        active_action = getattr(self.app, "active_action", None)
        if active_action:
            sdef = next((d for d in STAGE_DEFINITIONS if d["key"] == active_action), None)
            lbl = sdef["label"] if sdef else active_action
            worker_widget.update(f"[cyan]{self._spinner_frame()} {lbl} in progress...[/]")

        self.query_one("#dashboard-event-tail", Static).update(
            self._render_cached_event_tail(
                events,
                title="Recent Events",
                limit=self._event_tail_limit("#dashboard-event-tail"),
            )
        )

    def _refresh_dashboard(self) -> None:
        events = self._recent_events_for_refresh()
        snapshot = self._build_snapshot(events)

        session = getattr(self.app, "session", None)
        info_lines = ["[bold]Session[/bold]"]
        info_lines.append(f"  Release:  {snapshot.context.release_id or '[dim]not set[/]'}")
        info_lines.append(f"  Run:      {snapshot.context.run_id or '[dim]not set[/]'}")
        info_lines.append(f"  EPUB:     {snapshot.context.input_path or '[dim]not set[/]'}")
        if snapshot.context.chapter_start is not None or snapshot.context.chapter_end is not None:
            rng = f"Ch {snapshot.context.chapter_start or 1}\u2013{snapshot.context.chapter_end or 'end'}"
            info_lines.append(f"  Chapters: {rng}")

        if session and session.input_path and not self._fast_refresh_active():
            resolved = Path(session.input_path).expanduser().resolve()
            info_lines.append(f"  Resolved: {resolved}")
            info_lines.append(f"  Exists:   {'[green]yes[/]' if resolved.exists() else '[red]no[/]'}")
            info_lines.append(f"  Is .epub: {'[green]yes[/]' if resolved.suffix == '.epub' else '[red]no[/]'}")
        elif session and session.input_path:
            info_lines.append("  Path checks: [dim]paused while action runs[/]")

        self.query_one("#dashboard-session-info", Static).update("\n".join(info_lines))

        stage_lines = ["[bold]Stages[/bold]"]
        for stage in snapshot.stages:
            color = STATUS_COLORS.get(stage.status, "comment")
            glyph = STATUS_GLYPH.get(stage.status, "\u25cb")
            st = stage.status.upper()
            hint = f"  [{color}]{glyph}[/] {stage.label:<16} [{color}]{st:<7}[/]"
            if stage.action.reason:
                hint += f" [dim]({stage.action.reason})[/]"
            stage_lines.append(hint)
        self.query_one("#dashboard-stage-list", Static).update("\n".join(stage_lines))

        worker_widget = self.query_one("#dashboard-active-worker", Static)
        if snapshot.active_action:
            sdef = next((d for d in STAGE_DEFINITIONS if d["key"] == snapshot.active_action), None)
            lbl = sdef["label"] if sdef else snapshot.active_action
            worker_widget.update(f"[cyan]{self._spinner_frame()} {lbl} in progress...[/]")
        else:
            worker_widget.update("")

        failure_widget = self.query_one("#dashboard-latest-failure", Static)
        if snapshot.latest_failure:
            failure_widget.update(f"[red]Latest failure: {snapshot.latest_failure}[/]")
        else:
            failure_widget.update("")

        self.query_one("#dashboard-event-tail", Static).update(
            self._render_cached_event_tail(
                events,
                title="Recent Events",
                limit=self._event_tail_limit("#dashboard-event-tail"),
            )
        )

    def _render_cached_event_tail(self, events: list, *, title: str, limit: int = 5) -> str:
        return self._render_event_tail(events, title=title, limit=limit)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-new-file":
            self._on_new_file()
        elif event.button.id == "btn-resume-run":
            self._on_resume_run()

    def action_focus_prev_action(self) -> None:
        self.query_one("#btn-new-file", Button).focus()

    def action_focus_next_action(self) -> None:
        self.query_one("#btn-resume-run", Button).focus()

    def _on_new_file(self) -> None:
        from resemantica.tui.screens.run_dialog import NewFileDialog, NewFileResult

        def handle(result: NewFileResult | None) -> None:
            if result is None:
                self.notify("Session not initialised", severity="warning", timeout=3)
                return
            self.app.session.input_path = result.input_path
            self.app.session.chapter_start = result.chapter_start
            self.app.session.chapter_end = result.chapter_end
            self.app.set_ids(result.release_id, result.run_id)
            self.notify(
                f"Release: {result.release_id}, Run: {result.run_id}, File: {result.input_path.name}",
                severity="information",
                timeout=3,
            )
            self._refresh_dashboard()

        session = getattr(self.app, "session", None)
        self.app.push_screen(
            NewFileDialog(
                chapter_start=session.chapter_start if session else None,
                chapter_end=session.chapter_end if session else None,
            ),
            handle,
        )

    def _on_resume_run(self) -> None:
        from resemantica.tui.screens.run_dialog import ResumeRunDialog, ResumeRunResult

        def handle(result: ResumeRunResult | None) -> None:
            if result is None:
                self.notify("Session not initialised", severity="warning", timeout=3)
                return
            self.app.session.input_path = None
            self.app.session.chapter_start = result.chapter_start
            self.app.session.chapter_end = result.chapter_end
            self.app.set_ids(result.release_id, result.run_id)
            self.notify(
                f"Release: {result.release_id}, Run: {result.run_id}",
                severity="information",
                timeout=3,
            )
            self._refresh_dashboard()

        session = getattr(self.app, "session", None)
        self.app.push_screen(
            ResumeRunDialog(
                chapter_start=session.chapter_start if session else None,
                chapter_end=session.chapter_end if session else None,
            ),
            handle,
        )

    def _build_phase_progress(self, state: dict | None = None) -> str:
        return type(self)._build_phase_progress_static(state)

    @staticmethod
    def _build_phase_progress_static(state: dict | None) -> str:
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
            marker = "\u25a0" if done else "\u25b8" if s == current_stage else "\u25a1"
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
    def _format_event_summary(event: object) -> str:
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
        state: dict | None = None,
        events: list | None = None,
    ) -> str:
        state = self._get_run_state() if state is None else state
        if state is None:
            return "[dim]Quick stats unavailable without an active run.[/]"
        events = self._load_recent_run_events() if events is None else events
        return self._build_quick_stats_from_events(events)

    @staticmethod
    def _build_quick_stats_from_events(events: list) -> str:
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
