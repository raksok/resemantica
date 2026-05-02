from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static

from resemantica.tui.screens.base import BaseScreen
from resemantica.tui.screens.run_dialog import ConfirmDialog


class TranslationScreen(BaseScreen):
    BINDINGS = [
        Binding("t", "launch_translate", "Translate"),
        Binding("u", "launch_rebuild", "Rebuild"),
    ]

    def _content_widgets(self) -> ComposeResult:
        with Container(id="translation-content"):
            yield Static("Translation Progress", classes="app-title")
            yield Static("", id="translation-stage-list")
            yield Static("", id="translation-header")
            yield Static("", id="translation-block-list")
            yield Static("", id="translation-status")
            yield Static("", id="translation-event-tail", classes="event-tail")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_translation()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_translation()

    def _refresh_live_progress(self) -> None:
        super()._refresh_live_progress()
        self._update_status()
        self._update_event_tail()

    def _refresh_translation(self) -> None:
        state = self._run_state_for_refresh()

        stage_list = self.query_one("#translation-stage-list", Static)
        stage_list.update(self._build_stage_progress(state))

        header = self.query_one("#translation-header", Static)
        if state:
            header.update(
                f"[bold]Stage:[/] {state['stage_name']}\n"
                f"[bold]Status:[/] {state['status']}"
            )

        block_list = self.query_one("#translation-block-list", Static)
        if self._fast_refresh_active():
            block_list.update("[dim]Block progress updates resume when action completes.[/]")
        else:
            block_data = self._load_block_progress()
            if block_data:
                block_list.update(self._render_block_progress(block_data))
            else:
                block_list.update("[dim]No translation run active.[/]")

        self._update_status()
        self._update_event_tail()

    TRANSLATION_STAGE_KEYS = ["translate-range", "epub-rebuild"]

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
            if stage.key not in self.TRANSLATION_STAGE_KEYS:
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
        return "\n".join(lines)

    def _fallback_stage_progress(self, state: dict | None) -> str:
        lines: list[str] = ["[bold]Pipeline[/bold]"]
        for key, label in (("translate-range", "Translation"), ("epub-rebuild", "Rebuild")):
            if state and state.get("stage_name") == key:
                bar = self._running_bar(color="cyan")
                lines.append(f"  [cyan]\u25c9[/] {label:<14} {bar}  [cyan]RUNNING[/]")
            elif state and state.get("status") == "done":
                bar = self._static_bar(color="green", fill="\u2501")
                lines.append(f"  [green]\u25cf[/] {label:<14} {bar}  [green]DONE[/]")
            else:
                bar = self._static_bar(color="comment", fill="\u2500")
                lines.append(f"  [comment]\u25cb[/] {label:<14} {bar}  [comment]PENDING[/]")
        return "\n".join(lines)

    def _update_status(self) -> None:
        snapshot = self._build_snapshot()
        widget = self.query_one("#translation-status", Static)
        parts: list[str] = []
        if snapshot.active_action:
            from resemantica.tui.launch_control import STAGE_DEFINITIONS

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
        if parts:
            parts.append("")
        parts.append("[dim]t[/]=Translate  [dim]u[/]=Rebuild")
        widget.update("\n".join(parts))

    def _launch_stage(self, stage_key: str) -> None:
        adapter = self._make_adapter()
        if adapter is None:
            self.notify("Cannot launch: release/run not set", severity="error", timeout=3)
            return

        if stage_key == "translate-range":
            kwargs = self._chapter_scope_options()
            self.start_worker(
                stage_key,
                lambda stop_token=None: adapter.launch_stage(
                    stage_key,
                    **({"stop_token": stop_token} if stop_token is not None else {}),
                    **kwargs,
                ),
            )
        else:
            self.start_worker(
                stage_key,
                lambda stop_token=None: adapter.launch_stage(
                    stage_key,
                    **({"stop_token": stop_token} if stop_token is not None else {}),
                ),
            )

    def _confirm_then_launch(self, stage_key: str, message: str) -> None:
        def on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._launch_stage(stage_key)

        self.app.push_screen(ConfirmDialog("Confirm", message), on_confirm)

    def action_launch_translate(self) -> None:
        self._confirm_then_launch("translate-range", "Start Translation?")

    def action_launch_rebuild(self) -> None:
        self._confirm_then_launch("epub-rebuild", "Start EPUB rebuild?")

    def _update_event_tail(self) -> None:
        events = self._screen_events_for_tail()
        self.query_one("#translation-event-tail", Static).update(
            self._render_cached_event_tail(
                events,
                title="Translation Events",
                limit=self._event_tail_limit("#translation-event-tail"),
            )
        )

    def _render_cached_event_tail(self, events: list, *, title: str, limit: int = 5) -> str:
        return self._render_event_tail(events, title=title, limit=limit)

    def _event_source_mode(self) -> str:
        return "observability_stream"

    def _default_event_filter(self, event) -> bool:
        return self._is_translation_event(event)

    @staticmethod
    def _is_translation_event(event: object) -> bool:
        stage_name = str(getattr(event, "stage_name", "") or "").lower()
        event_type = str(getattr(event, "event_type", "") or "").lower()
        if stage_name in {"translate-range", "translate-chapter"}:
            return True
        if "translate" in event_type or "pass" in event_type or "block" in event_type:
            return True
        return "chapter" in event_type and stage_name.startswith("translate")

    def _load_block_progress(self) -> dict[int, list[tuple[str, str]]]:
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if not release_id or not run_id:
            return {}
        try:
            from resemantica.tracking.repo import ensure_tracking_db, load_events

            conn = ensure_tracking_db(release_id)
            try:
                events = load_events(conn, run_id=run_id, release_id=release_id, limit=500)
                chapters: dict[int, dict[str, str]] = {}
                for ev in reversed(events):
                    if ev.chapter_number is None:
                        continue
                    blocks = chapters.setdefault(ev.chapter_number, {})
                    if ev.block_id:
                        if "completed" in (ev.event_type or "") or "complete" in (ev.event_type or ""):
                            blocks[ev.block_id] = "done"
                        elif "fail" in (ev.event_type or "").lower():
                            blocks[ev.block_id] = "failed"
                        elif ev.block_id not in blocks:
                            blocks[ev.block_id] = "in-progress"
                return {ch: sorted(blks.items()) for ch, blks in chapters.items()}
            finally:
                conn.close()
        except Exception:
            return {}

    @staticmethod
    def _render_block_progress(data: dict[int, list[tuple[str, str]]]) -> str:
        if not data:
            return "[dim]No translation run active.[/]"
        lines: list[str] = []
        for ch_num in sorted(data):
            blocks = data[ch_num]
            done = sum(1 for _, s in blocks if s == "done")
            lines.append(f"[bold]Ch {ch_num}[/]  {done}/{len(blocks)} blocks")
            for bid, status in blocks[:15]:
                char = "\u25a0" if status == "done" else "\u2717" if status == "failed" else "\u25b8"
                color = "green" if status == "done" else "red" if status == "failed" else "cyan"
                lines.append(f"  [{color}]{char}[/] {bid}")
            if len(blocks) > 15:
                lines.append(f"  ... +{len(blocks) - 15} more")
        return "\n".join(lines)
