from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static

from resemantica.tui.screens.base import BaseScreen


class TranslationScreen(BaseScreen):
    BINDINGS = [
        Binding("t", "launch_translate", "Translate"),
        Binding("u", "launch_rebuild", "Rebuild"),
    ]

    def _content_widgets(self) -> ComposeResult:
        with Container(id="translation-content"):
            yield Static("Translation Progress", classes="app-title")
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

    def _refresh_translation(self) -> None:
        state = self._get_run_state()

        header = self.query_one("#translation-header", Static)
        if state:
            header.update(
                f"[bold]Stage:[/] {state['stage_name']}\n"
                f"[bold]Status:[/] {state['status']}"
            )
        else:
            header.update("[dim]No translation run active.[/]")

        block_list = self.query_one("#translation-block-list", Static)
        block_data = self._load_block_progress()
        if block_data:
            block_list.update(self._render_block_progress(block_data))
        else:
            block_list.update("[dim]No translation run active.[/]")

        self._update_status()
        self._update_event_tail()

    def _update_status(self) -> None:
        snapshot = self._build_snapshot()
        widget = self.query_one("#translation-status", Static)
        parts: list[str] = []
        if snapshot.active_action:
            parts.append(f"[cyan]{self._spinner_frame()} {snapshot.active_action} in progress...[/]")
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
            self.start_worker(stage_key, lambda: adapter.launch_stage(stage_key, **kwargs))
        else:
            self.start_worker(stage_key, lambda: adapter.launch_stage(stage_key))

    def action_launch_translate(self) -> None:
        self._launch_stage("translate-range")

    def action_launch_rebuild(self) -> None:
        self._launch_stage("epub-rebuild")

    def _update_event_tail(self) -> None:
        events = [
            event
            for event in self._load_recent_run_events()
            if self._is_translation_event(event)
        ]
        self.query_one("#translation-event-tail", Static).update(
            self._render_event_tail(events, title="Translation Events")
        )

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
