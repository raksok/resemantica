from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static

from resemantica.tui.launch_control import STAGE_DEFINITIONS
from resemantica.tui.screens.base import BaseScreen
from resemantica.tui.screens.run_dialog import ConfirmDialog


class IngestionScreen(BaseScreen):
    BINDINGS = [
        Binding("e", "launch_extract", "Extract"),
    ]

    def _content_widgets(self) -> ComposeResult:
        with Container(id="ingestion-content"):
            yield Static("Ingestion / Extraction", classes="app-title")
            yield Static("", id="ingestion-stage-list")
            yield Static("", id="ingestion-status")
            yield Static("", id="ingestion-event-tail", classes="event-tail")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_ingestion()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_ingestion()

    def _refresh_live_progress(self) -> None:
        super()._refresh_live_progress()
        self._update_status()
        self._update_event_tail()

    def _refresh_ingestion(self) -> None:
        state = self._run_state_for_refresh()
        stage_list = self.query_one("#ingestion-stage-list", Static)
        stage_list.update(self._build_stage_progress(state))
        self._update_status()
        self._update_event_tail()

    def _build_stage_progress(self, state: dict | None = None) -> str:
        if state is None and not self._fast_refresh_active():
            state = self._get_run_state()
        try:
            events = self._recent_events_for_refresh()
            snapshot = self._build_snapshot(run_state=state)
            return self._render_stages_from_snapshot(snapshot, events=events)
        except Exception:
            return self._fallback_stage_progress(state)

    def _render_stages_from_snapshot(
        self,
        snapshot,
        *,
        events=None,
    ) -> str:
        progress = self._derive_stage_progress(events or [])
        lines: list[str] = ["[bold]Pipeline[/bold]"]
        for stage in snapshot.stages:
            if stage.key != "epub-extract":
                continue
            color = {
                "missing": "comment",
                "ready": "green",
                "running": "cyan",
                "done": "green",
                "failed": "red",
                "blocked": "orange",
                "stale": "orange",
                "disabled": "dim",
            }.get(stage.status, "comment")
            glyph = {
                "missing": "\u25cb",
                "ready": "\u25c9",
                "running": "\u25c9",
                "done": "\u25cf",
                "failed": "\u2717",
                "blocked": "\u2298",
                "stale": "\u25c9",
                "disabled": "\u25cb",
            }.get(stage.status, "\u25cb")
            stage_progress = progress.get(stage.key)
            if stage_progress and stage_progress.has_progress:
                bar = self._render_scoped_bar(stage_progress, stage.status)
                numeric = f" {stage_progress.completed}/{stage_progress.total}"
            elif stage.status == "done":
                bar = self._static_bar(color="green", fill="\u2501")
                numeric = ""
            elif stage.status == "running":
                bar = self._running_bar(color="cyan")
                numeric = ""
            else:
                bar = self._static_bar(color="comment", fill="\u2500")
                numeric = ""
            lines.append(
                f"  [{color}]{glyph}[/] {stage.label:<14} {bar}{numeric:<6}  [{color}]{stage.status.upper():<7}[/]"
            )
        lines.append("")
        lines.append("[dim]e[/]=Extract")
        return "\n".join(lines)

    def _fallback_stage_progress(self, state: dict | None) -> str:
        lines: list[str] = ["[bold]Pipeline[/bold]"]
        label = "EPUB Extract"
        if state and state.get("stage_name") == "epub-extract":
            bar = self._running_bar(color="cyan")
            lines.append(f"  [cyan]\u25c9[/] {label:<14} {bar}  [cyan]RUNNING[/]")
        elif state and state.get("status") == "done":
            bar = self._static_bar(color="green", fill="\u2501")
            lines.append(f"  [green]\u25cf[/] {label:<14} {bar}  [green]DONE[/]")
        else:
            bar = self._static_bar(color="comment", fill="\u2500")
            lines.append(f"  [comment]\u25cb[/] {label:<14} {bar}  [comment]PENDING[/]")
        lines.append("")
        lines.append("[dim]e[/]=Extract")
        return "\n".join(lines)

    def _update_status(self) -> None:
        snapshot = self._build_snapshot()
        widget = self.query_one("#ingestion-status", Static)
        parts: list[str] = []
        if snapshot.active_action == "epub-extract":
            sdef = next(
                (d for d in STAGE_DEFINITIONS if d["key"] == snapshot.active_action),
                None,
            )
            lbl = sdef["label"] if sdef else snapshot.active_action
            if getattr(self.app, "active_stop_requested", False):
                parts.append(f"[cyan]{self._spinner_frame()} Stopping after current chapter...[/]")
            else:
                parts.append(f"[cyan]{self._spinner_frame()} {lbl} in progress...[/]")
        if snapshot.latest_failure:
            parts.append(f"[red]Failure: {snapshot.latest_failure}[/]")
        widget.update("\n".join(parts) if parts else "")

    def _update_event_tail(self) -> None:
        events = self._screen_events_for_tail()
        self.query_one("#ingestion-event-tail", Static).update(
            self._render_cached_event_tail(
                events,
                title="Extraction Events",
                limit=self._event_tail_limit("#ingestion-event-tail"),
            )
        )

    def _render_cached_event_tail(self, events: list, *, title: str, limit: int = 5) -> str:
        return self._render_event_tail(events, title=title, limit=limit)

    def _event_source_mode(self) -> str:
        return "observability_stream"

    def _default_event_filter(self, event) -> bool:
        return self._event_matches_stage_prefix(event, ("epub-extract",))

    def action_launch_extract(self) -> None:
        session = getattr(self.app, "session", None)
        input_path = session.input_path if session else None
        if not input_path:
            self.notify("No EPUB path selected — set one on Dashboard first", severity="error", timeout=3)
            return

        adapter = self._make_adapter()
        if adapter is None:
            self.notify("Cannot launch: release/run not set", severity="error", timeout=3)
            return

        def on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                resolved = Path(input_path).expanduser().resolve()
                self.start_worker("epub-extract", lambda stop_token=None: adapter.extract_epub(resolved))

        self.app.push_screen(ConfirmDialog("Confirm", "Start EPUB extraction?"), on_confirm)
