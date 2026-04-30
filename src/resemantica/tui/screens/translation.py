from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from resemantica.tui.screens.base import BaseScreen


class TranslationScreen(BaseScreen):
    def _content_widgets(self) -> ComposeResult:
        with Container(id="translation-content"):
            yield Static("Translation Progress", classes="app-title")
            yield Static("", id="translation-header")
            yield Static("", id="translation-block-list")
            yield Static("", id="translation-launch-control")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_translation()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_translation()

    def _refresh_translation(self) -> None:
        header = self.query_one("#translation-header", Static)
        state = self._get_run_state()
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

        self._update_launch_control()

    def _update_launch_control(self) -> None:
        control = self.query_one("#translation-launch-control", Static)
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if release_id and run_id:
            control.update("[green]\\[t\\] Launch Translation[/]")
        else:
            control.update("[comment]\\[t\\] Launch Translation (set release/run first)[/]")

    def key_t(self) -> None:
        adapter = self._make_adapter()
        if adapter is None:
            return
        control = self.query_one("#translation-launch-control", Static)
        control.update("[cyan]Translation started...[/]")
        from threading import Thread

        def _run() -> None:
            try:
                adapter.launch_workflow("translation")
                self.app.call_from_thread(
                    control.update, "[green]Translation completed.[/]"
                )
            except Exception as e:
                self.app.call_from_thread(
                    control.update, f"[red]Launch failed: {e}[/]"
                )

        Thread(target=_run, daemon=True).start()

    def _load_block_progress(self) -> dict[int, list[tuple[str, str]]]:
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if not release_id or not run_id:
            return {}
        try:
            from resemantica.tracking.repo import ensure_tracking_db, load_events

            conn = ensure_tracking_db(release_id)
            try:
                events = load_events(
                    conn, run_id=run_id, release_id=release_id, limit=500
                )
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
                char = "■" if status == "done" else "✗" if status == "failed" else "▸"
                color = "green" if status == "done" else "red" if status == "failed" else "cyan"
                lines.append(f"  [{color}]{char}[/] {bid}")
            if len(blocks) > 15:
                lines.append(f"  ... +{len(blocks) - 15} more")
        return "\n".join(lines)
