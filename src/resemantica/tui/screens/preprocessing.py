from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static

from resemantica.tui.launch_control import STAGE_DEFINITIONS, LaunchSnapshot
from resemantica.tui.screens.base import BaseScreen

PREPRO_STAGE_KEYS = [
    "epub-extract",
    "preprocess-glossary",
    "preprocess-summaries",
    "preprocess-idioms",
    "preprocess-graph",
    "packets-build",
]


@dataclass(frozen=True)
class _ProgressModel:
    total: int | None = None
    completed: int = 0
    active_chapter: int | None = None

    @property
    def has_progress(self) -> bool:
        return self.total is not None


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
            yield Static("", id="preprocessing-event-tail", classes="event-tail")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_preprocessing()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_preprocessing()

    def _refresh_live_progress(self) -> None:
        super()._refresh_live_progress()
        self._update_status()
        self._update_event_tail()

    def _refresh_preprocessing(self) -> None:
        state = self._run_state_for_refresh()
        stage_list = self.query_one("#preprocessing-stage-list", Static)
        stage_list.update(self._build_stage_progress(state))
        self._update_status()
        self._update_event_tail()

    def _build_stage_progress(self, state: dict | None = None) -> str:
        if state is None and not self._fast_refresh_active():
            state = self._get_run_state()
        try:
            events = self._recent_events_for_refresh()
            snapshot = self._snapshot(state)
            return self._render_stages_from_snapshot(snapshot, events=events)
        except Exception:
            return self._fallback_stage_progress(state)

    def _snapshot(self, state: dict | None = None) -> LaunchSnapshot:
        return self._build_snapshot(run_state=state)

    def _render_stages_from_snapshot(
        self,
        snapshot: LaunchSnapshot,
        *,
        events: list[Any] | None = None,
    ) -> str:
        progress = self._derive_progress_models(events or [])
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
            if stage.key == "preprocess-glossary":
                for phase_key, phase_label in (
                    ("preprocess-glossary.discover", "discover"),
                    ("preprocess-glossary.translate", "translate"),
                    ("preprocess-glossary.promote", "promote"),
                ):
                    phase_progress = progress.get(phase_key)
                    if phase_progress is None or not phase_progress.has_progress:
                        continue
                    phase_status = "done" if phase_progress.completed >= (phase_progress.total or 0) else stage.status
                    phase_bar = self._render_scoped_bar(phase_progress, phase_status)
                    lines.append(
                        f"      [comment]{phase_label:<10}[/] {phase_bar} "
                        f"{phase_progress.completed}/{phase_progress.total}"
                    )
        lines.append("")
        lines.append("[dim]g[/]=Glossary  [dim]s[/]=Summaries  [dim]i[/]=Idioms  [dim]r[/]=Graph  [dim]b[/]=Packets")
        return "\n".join(lines)

    @classmethod
    def _derive_progress_models(cls, events: list[Any]) -> dict[str, _ProgressModel]:
        deduped: dict[str, Any] = {}
        for event in events:
            event_id = str(getattr(event, "event_id", ""))
            if not event_id:
                event_id = repr(
                    (
                        getattr(event, "event_time", ""),
                        getattr(event, "event_type", ""),
                        getattr(event, "chapter_number", None),
                    )
                )
            deduped[event_id] = event

        ordered = sorted(
            deduped.values(),
            key=lambda event: (str(getattr(event, "event_time", "")), str(getattr(event, "event_id", ""))),
        )
        totals: dict[str, int] = {}
        completed: dict[str, set[int]] = {}
        active: dict[str, int] = {}

        for event in ordered:
            event_type = str(getattr(event, "event_type", "") or "")
            payload = getattr(event, "payload", {}) or {}
            total = payload.get("total_chapters") if isinstance(payload, dict) else None
            if event_type.endswith(".started"):
                stage_key = event_type.removesuffix(".started")
                if isinstance(total, int):
                    totals[stage_key] = total
                elif stage_key.endswith(".promote"):
                    totals[stage_key] = 1
                continue

            if event_type.endswith(".chapter_started"):
                stage_key = event_type.removesuffix(".chapter_started")
                chapter_number = getattr(event, "chapter_number", None)
                if isinstance(chapter_number, int):
                    active[stage_key] = chapter_number
                continue

            if event_type.endswith(".chapter_completed") or event_type.endswith(".chapter_skipped"):
                stage_key = event_type.rsplit(".", 1)[0]
                chapter_number = getattr(event, "chapter_number", None)
                if isinstance(chapter_number, int):
                    completed.setdefault(stage_key, set()).add(chapter_number)
                    if active.get(stage_key) == chapter_number:
                        active.pop(stage_key, None)
                continue

            if event_type.endswith(".promote.completed"):
                completed.setdefault(event_type.removesuffix(".completed"), set()).add(1)

        models: dict[str, _ProgressModel] = {}
        for stage_key, total in totals.items():
            done = completed.get(stage_key, set())
            models[stage_key] = _ProgressModel(
                total=total,
                completed=min(len(done), total),
                active_chapter=active.get(stage_key),
            )

        glossary_phase = next(
            (
                models[key]
                for key in (
                    "preprocess-glossary.promote",
                    "preprocess-glossary.translate",
                    "preprocess-glossary.discover",
                )
                if key in models
                and (
                    models[key].completed < (models[key].total or 0)
                    or key == "preprocess-glossary.promote"
                )
            ),
            models.get("preprocess-glossary.discover"),
        )
        if glossary_phase is not None:
            models["preprocess-glossary"] = glossary_phase

        return models

    @staticmethod
    def _render_scoped_bar(model: _ProgressModel, status: str) -> str:
        width = 20
        total = max(1, model.total or 0)
        completed = min(max(0, model.completed), total)
        if completed >= total:
            return "[green]\u2501" + "\u2501" * (width - 1) + "[/]"
        filled = int((completed / total) * width)
        has_active = model.active_chapter is not None or status == "running"
        marker = "\u257a" if has_active else "\u2500"
        empty = max(0, width - filled - (1 if has_active else 0))
        color = "cyan" if status == "running" or has_active else "comment"
        filled_text = "\u2501" * filled
        marker_text = marker if has_active else ""
        empty_text = "\u2500" * empty
        return f"[{color}]{filled_text}{marker_text}{empty_text}[/]"

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
            return PreprocessingScreen._static_bar(color="green", fill="\u2501")
        if status == "RUNNING":
            return PreprocessingScreen._running_bar(color="cyan")
        return PreprocessingScreen._static_bar(color="comment", fill="\u2500")

    @staticmethod
    def _static_bar(*, color: str, fill: str, width: int = 20) -> str:
        return f"[{color}]{fill * width}[/]"

    @staticmethod
    def _running_bar(*, color: str, width: int = 20) -> str:
        filled = "\u2501" * 8
        marker = "\u257a"
        remaining = "\u2500" * (width - len(filled) - 1)
        return f"[{color}]{filled}{marker}{remaining}[/]"

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
            if getattr(self.app, "active_stop_requested", False):
                parts.append(f"[cyan]{self._spinner_frame()} Stopping after current chapter...[/]")
            else:
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
            self.start_worker(stage_key, lambda stop_token=None: adapter.extract_epub(resolved))
        else:
            options = self._chapter_scope_options()
            self.start_worker(
                stage_key,
                lambda stop_token=None: adapter.launch_stage(
                    stage_key,
                    **({"stop_token": stop_token} if stop_token is not None else {}),
                    **options,
                ),
            )

    def _update_event_tail(self) -> None:
        events = self._screen_events_for_tail()
        self.query_one("#preprocessing-event-tail", Static).update(
            self._render_cached_event_tail(
                events,
                title="Preprocessing Events",
                limit=self._event_tail_limit("#preprocessing-event-tail"),
            )
        )

    def _render_cached_event_tail(self, events: list, *, title: str, limit: int = 5) -> str:
        return self._render_event_tail(events, title=title, limit=limit)

    def _event_source_mode(self) -> str:
        return "observability_stream"

    def _default_event_filter(self, event) -> bool:
        return self._event_matches_stage_prefix(event, ("preprocess-", "packets-build"))

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
