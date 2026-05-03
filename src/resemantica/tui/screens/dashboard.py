from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static

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
    "missing": "\u25cb",
    "ready": "\u25c9",
    "running": "\u25c9",
    "done": "\u25cf",
    "failed": "\u2717",
    "blocked": "\u2298",
    "stale": "\u25c9",
    "disabled": "\u25cb",
}


class DashboardScreen(BaseScreen):
    BINDINGS = [
        Binding("n", "new_file", "New File"),
        Binding("r", "resume_run", "Resume"),
        Binding("c", "set_scope", "Scope"),
        Binding("f", "toggle_force", "Force"),
        Binding("d", "toggle_dry_run", "Dry-Run"),
        Binding("p", "launch_production", "Production"),
    ]

    def _content_widgets(self) -> ComposeResult:
        with Container(id="dashboard-content"):
            with Horizontal(id="dashboard-main"):
                with Vertical(id="dashboard-left"):
                    yield Static("Dashboard", classes="app-title")
                    yield Static("", id="dashboard-key-hints")
                    yield Static("", id="dashboard-session-info")
                    yield Static("", id="dashboard-stage-list")
                    yield Static("", id="dashboard-active-worker")
                    yield Static("", id="dashboard-latest-failure")
                    yield Static("", id="dashboard-recent-runs")
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
        snapshot = self._build_snapshot(events)

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

    def _refresh_dashboard(self) -> None:
        events = self._recent_events_for_refresh()
        snapshot = self._build_snapshot(events)

        key_hints = (
            "[dim][n][/] New File    [dim][r][/] Resume Run\n"
            "[dim][c][/] Scope       [dim][f][/] Force    [dim][d][/] Dry-Run\n"
            "[dim][p][/] Production"
        )
        self.query_one("#dashboard-key-hints", Static).update(key_hints)

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

        flags = []
        if getattr(self, "_force", False):
            flags.append("[orange]FORCE[/]")
        if getattr(self, "_dry_run", False):
            flags.append("[yellow]DRY-RUN[/]")
        if flags:
            worker_widget.update(f"{' '.join(flags)}")

        recent = self._build_recent_runs()
        self.query_one("#dashboard-recent-runs", Static).update(recent)

        self.query_one("#dashboard-event-tail", Static).update(
            self._render_cached_event_tail(
                events,
                title="Recent Events",
                limit=self._event_tail_limit("#dashboard-event-tail"),
            )
        )

    def _build_recent_runs(self) -> str:
        release_id = self._get_release_id()
        if not release_id:
            return "[dim]No recent runs.[/]"
        try:
            from resemantica.tracking.repo import ensure_tracking_db

            conn = ensure_tracking_db(release_id)
            try:
                cursor = conn.execute(
                    "SELECT run_id, stage_name, status FROM run_state ORDER BY started_at DESC LIMIT 5"
                )
                rows = cursor.fetchall()
                if not rows:
                    return "[dim]No recent runs.[/]"
                lines = ["[bold]Recent Runs[/bold]"]
                for run_id, stage_name, status in rows:
                    color = "green" if status == "completed" else "red" if status == "failed" else "cyan"
                    lines.append(f"  [{color}]{run_id:<20}[/] {stage_name or '--':<16} {status}")
                return "\n".join(lines)
            finally:
                conn.close()
        except Exception:
            return "[dim]No recent runs.[/]"

    def _render_cached_event_tail(self, events: list, *, title: str, limit: int = 5) -> str:
        return self._render_event_tail(events, title=title, limit=limit)

    def action_new_file(self) -> None:
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
                f"Release: {result.release_id}, Run: {result.run_id}",
                severity="information", timeout=3,
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

    def action_resume_run(self) -> None:
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
                severity="information", timeout=3,
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

    def action_set_scope(self) -> None:
        from resemantica.tui.screens.run_dialog import ChapterScopeDialog, ChapterScopeResult

        def handle(result: ChapterScopeResult | None) -> None:
            if result is None:
                return
            self.app.session.chapter_start = result.chapter_start
            self.app.session.chapter_end = result.chapter_end
            self._refresh_dashboard()

        session = getattr(self.app, "session", None)
        self.app.push_screen(
            ChapterScopeDialog(
                chapter_start=session.chapter_start if session else None,
                chapter_end=session.chapter_end if session else None,
            ),
            handle,
        )

    def action_toggle_force(self) -> None:
        self._force = not getattr(self, "_force", False)
        status = "ON" if self._force else "OFF"
        self.notify(f"Force re-run: {status}", timeout=2)

    def action_toggle_dry_run(self) -> None:
        self._dry_run = not getattr(self, "_dry_run", False)
        status = "ON" if self._dry_run else "OFF"
        self.notify(f"Dry-run mode: {status}", timeout=2)

    def action_launch_production(self) -> None:
        adapter = self._make_adapter()
        if adapter is None:
            self.notify("Cannot launch: release/run not set", severity="error", timeout=3)
            return
        options = self._chapter_scope_options()
        options["force"] = getattr(self, "_force", False)
        options["dry_run"] = getattr(self, "_dry_run", False)
        self.start_worker(
            "production",
            lambda stop_token=None: adapter.launch_production(
                **({"stop_token": stop_token} if stop_token is not None else {}),
                **options,
            ),
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
