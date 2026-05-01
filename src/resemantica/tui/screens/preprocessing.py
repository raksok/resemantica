from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from resemantica.tui.screens.base import BaseScreen


class PreprocessingScreen(BaseScreen):
    def _content_widgets(self) -> ComposeResult:
        with Container(id="preprocessing-content"):
            yield Static("Preprocessing Stages", classes="app-title")
            yield Static("", id="preprocessing-stage-list")
            yield Static("", id="preprocessing-launch-control")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_preprocessing()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_preprocessing()

    def _refresh_preprocessing(self) -> None:
        stage_list = self.query_one("#preprocessing-stage-list", Static)
        stage_list.update(self._build_stage_progress())
        self._update_launch_control()

    def _update_launch_control(self) -> None:
        control = self.query_one("#preprocessing-launch-control", Static)
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if release_id and run_id:
            control.update("[green]\\[p\\] Launch Preprocessing[/]")
        else:
            control.update("[comment]\\[p\\] Launch Preprocessing (set release/run first)[/]")

    def key_p(self) -> None:
        adapter = self._make_adapter()
        if adapter is None:
            return
        control = self.query_one("#preprocessing-launch-control", Static)
        control.update("[cyan]Preprocessing started...[/]")
        from threading import Thread

        def _run() -> None:
            try:
                adapter.launch_workflow("preprocessing")
                self.app.call_from_thread(
                    control.update, "[green]Preprocessing completed.[/]"
                )
            except Exception as e:
                self.app.call_from_thread(
                    control.update, f"[red]Launch failed: {e}[/]"
                )

        Thread(target=_run, daemon=True).start()

    def _build_stage_progress(self, state: dict | None = None) -> str:
        if state is None:
            state = self._get_run_state()
        stages = [
            ("EPUB Extract", "preprocess-epub"),
            ("Glossary", "preprocess-glossary"),
            ("Summaries", "preprocess-summaries"),
            ("Idioms", "preprocess-idioms"),
            ("Graph MVP", "preprocess-graph"),
            ("Packets", "packets-build"),
        ]
        current_stage = state["stage_name"] if state else None
        stage_order = [
            "preprocess-glossary",
            "preprocess-summaries",
            "preprocess-idioms",
            "preprocess-graph",
            "packets-build",
        ]
        lines: list[str] = ["[bold]Pipeline[/bold]"]
        for label, stage_key in stages:
            if stage_key == "preprocess-epub":
                status = "DONE"
                color = "green"
            elif stage_key == "packets-build":
                if current_stage and stage_key in stage_order:
                    idx = stage_order.index(stage_key)
                    curr_idx = stage_order.index(current_stage) if current_stage in stage_order else -1
                    if idx < curr_idx:
                        status, color = "DONE", "green"
                    elif idx == curr_idx:
                        status, color = "RUNNING", "cyan"
                    else:
                        status, color = "PENDING", "comment"
                else:
                    status, color = "PENDING", "comment"
            else:
                if current_stage and stage_key in stage_order:
                    idx = stage_order.index(stage_key)
                    curr_idx = stage_order.index(current_stage) if current_stage in stage_order else -1
                    if idx < curr_idx:
                        status, color = "DONE", "green"
                    elif idx == curr_idx:
                        status, color = "RUNNING", "cyan"
                    else:
                        status, color = "PENDING", "comment"
                else:
                    status, color = "PENDING", "comment"
            marker = {"DONE": "●", "RUNNING": "◉", "PENDING": "○"}[status]
            bar = self._render_stage_bar(status)
            lines.append(
                f"  [{color}]{marker}[/] {label:<14} {bar}  [{color}]{status:<7}[/]"
            )
        return "\n".join(lines)

    @staticmethod
    def _render_stage_bar(status: str) -> str:
        if status == "DONE":
            return "[green]━━━━━━━━━━━━━━━━━━━━[/]"
        if status == "RUNNING":
            return "[cyan]━━━━━━━━━━╺─────────[/]"
        return "[comment]────────────────────[/]"
