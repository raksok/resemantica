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

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_preprocessing()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_preprocessing()

    def _refresh_preprocessing(self) -> None:
        stage_list = self.query_one("#preprocessing-stage-list", Static)
        stage_list.update(self._build_stage_progress())

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
        lines: list[str] = []
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
            bar_len = 20
            filled = bar_len if status == "DONE" else bar_len // 2 if status == "RUNNING" else 0
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(f"  {label:20s} [{color}]{bar}[/]  [{color}]{status}[/]")
        return "\n".join(lines)
