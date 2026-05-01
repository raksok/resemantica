from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static

from resemantica.tui.launch_control import LaunchSnapshot, STAGE_DEFINITIONS
from resemantica.tui.screens.base import BaseScreen

PREPRO_STAGE_KEYS = [
    "epub-extract",
    "preprocess-glossary",
    "preprocess-summaries",
    "preprocess-idioms",
    "preprocess-graph",
    "packets-build",
]


class PreprocessingScreen(BaseScreen):
    BINDINGS = [
        Binding("g", "launch_glossary", "Glossary"),
        Binding("s", "launch_summaries", "Summaries"),
        Binding("i", "launch_idioms", "Idioms"),
        Binding("r", "launch_graph", "Graph"),
        Binding("b", "launch_packets", "Packets"),
    ]

    def _content_widgets(self) -> ComposeResult:
        with Container(id="preprocessing-content"):
            yield Static("Preprocessing Stages", classes="app-title")
            yield Static("", id="preprocessing-stage-list")
            yield Static("", id="preprocessing-status")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_preprocessing()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_preprocessing()

    def _refresh_preprocessing(self) -> None:
        state = self._get_run_state()
        stage_list = self.query_one("#preprocessing-stage-list", Static)
        stage_list.update(self._build_stage_progress(state))
        self._update_status()

    def _build_stage_progress(self, state: dict | None = None) -> str:
        if state is None:
            state = self._get_run_state()
        try:
            snapshot = self._snapshot(state)
            return self._render_stages_from_snapshot(snapshot)
        except Exception:
            return self._fallback_stage_progress(state)

    def _snapshot(self, state: dict | None = None) -> LaunchSnapshot:
        return self._build_snapshot(run_state=state)

    def _render_stages_from_snapshot(self, snapshot: LaunchSnapshot) -> str:
        lines: list[str] = ["[bold]Pipeline[/bold]"]
        for stage in snapshot.stages:
            if stage.key not in PREPRO_STAGE_KEYS:
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
            if stage.status == "done":
                bar = "[green]\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501[/]"
            elif stage.status == "running":
                bar = "[cyan]\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u257a\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/]"
            else:
                bar = "[comment]\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/]"
            lines.append(
                f"  [{color}]{glyph}[/] {stage.label:<14} {bar}  [{color}]{stage.status.upper():<7}[/]"
            )
        lines.append("")
        lines.append("[dim]g[/]=Glossary  [dim]s[/]=Summaries  [dim]i[/]=Idioms  [dim]r[/]=Graph  [dim]b[/]=Packets")
        return "\n".join(lines)

    def _fallback_stage_progress(self, state: dict | None) -> str:
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
                status, color = "DONE", "green"
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
            marker = {"DONE": "\u25cf", "RUNNING": "\u25c9", "PENDING": "\u25cb"}[status]
            bar = self._render_stage_bar(status)
            lines.append(f"  [{color}]{marker}[/] {label:<14} {bar}  [{color}]{status:<7}[/]")
        return "\n".join(lines)

    @staticmethod
    def _render_stage_bar(status: str) -> str:
        if status == "DONE":
            return "[green]\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501[/]"
        if status == "RUNNING":
            return "[cyan]\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u257a\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/]"
        return "[comment]\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/]"

    def _update_status(self) -> None:
        snapshot = self._snapshot()
        widget = self.query_one("#preprocessing-status", Static)
        parts: list[str] = []
        if snapshot.active_action:
            sdef = next(
                (d for d in STAGE_DEFINITIONS if d["key"] == snapshot.active_action),
                None,
            )
            lbl = sdef["label"] if sdef else snapshot.active_action
            parts.append(f"[cyan]{self._spinner_frame()} {lbl} in progress...[/]")
        if snapshot.latest_failure:
            parts.append(f"[red]Failure: {snapshot.latest_failure}[/]")
        widget.update("\n".join(parts) if parts else "")

    def _launch_stage(self, stage_key: str) -> None:
        adapter = self._make_adapter()
        if adapter is None:
            self.notify("Cannot launch: release/run not set", severity="error", timeout=3)
            return

        if stage_key == "epub-extract":
            session = getattr(self.app, "session", None)
            input_path = session.input_path if session else None
            if not input_path:
                self.notify("No EPUB path selected", severity="error", timeout=3)
                return
            resolved = Path(input_path).expanduser().resolve()
            self.start_worker(stage_key, lambda: adapter.extract_epub(resolved))
        else:
            self.start_worker(stage_key, lambda: adapter.launch_stage(stage_key))

    def action_launch_glossary(self) -> None:
        self._launch_stage("preprocess-glossary")

    def action_launch_summaries(self) -> None:
        self._launch_stage("preprocess-summaries")

    def action_launch_idioms(self) -> None:
        self._launch_stage("preprocess-idioms")

    def action_launch_graph(self) -> None:
        self._launch_stage("preprocess-graph")

    def action_launch_packets(self) -> None:
        self._launch_stage("packets-build")
