from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TaskProgressColumn, TextColumn
from rich.rule import Rule
from rich.text import Text

from resemantica.logging_config import replace_stderr_sink, restore_stderr_sink
from resemantica.observability.granularity import classify_event_level, cli_verbosity_to_level
from resemantica.orchestration.events import default_event_bus
from resemantica.tracking.models import Event


class CliProgressSubscriber:
    def __init__(
        self,
        *,
        event_bus: Any = default_event_bus,
        progress: Progress | None = None,
        verbosity: int = 0,
        log_lines: int = 10,
    ) -> None:
        self.event_bus = event_bus
        self._level = cli_verbosity_to_level(verbosity)
        self._verbosity = verbosity
        self._log_lines = log_lines
        self._injected_progress = progress

        self.tasks_by_stage: dict[str, TaskID] = {}
        self.warning_count = 0
        self.skip_count = 0
        self.retry_count = 0
        self.artifact_count = 0

        self._log_buffer: deque[str] = deque(maxlen=log_lines)
        self._log_lock = Lock()
        self._live: Live | None = None
        self.progress: Progress | None = progress

    def __enter__(self) -> CliProgressSubscriber:
        self.event_bus.subscribe("*", self._on_event)

        if self._injected_progress:
            self.progress = self._injected_progress
            self.progress.start()
        else:
            self.progress = Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                BarColumn(),
                TaskProgressColumn(show_speed=False),
            )
            self._live = Live(self._render_layout, refresh_per_second=4, stderr=True, auto_clear=False)
            self._live.__enter__()
            replace_stderr_sink(self._log_sink, fmt="{message}")

        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.event_bus.unsubscribe("*", self._on_event)

        if self._injected_progress:
            self.progress.stop()
        else:
            self._live.__exit__(exc_type, exc_val, exc_tb)
            restore_stderr_sink()

    def _counter_text(self) -> str:
        pairs: list[str] = []
        if self.warning_count:
            pairs.append(f"warn {self.warning_count}")
        if self.skip_count:
            pairs.append(f"skip {self.skip_count}")
        if self.retry_count:
            pairs.append(f"retry {self.retry_count}")
        if self.artifact_count:
            pairs.append(f"artifacts {self.artifact_count}")
        return " ".join(pairs)

    def _render_status(self) -> Text:
        pairs: list[str] = []
        if self.skip_count:
            pairs.append(f"skip: {self.skip_count}")
        if self.warning_count:
            pairs.append(f"warn: {self.warning_count}")
        if self.retry_count:
            pairs.append(f"retry: {self.retry_count}")
        if self.artifact_count:
            pairs.append(f"artifacts: {self.artifact_count}")
        return Text("  |  ".join(pairs))

    def _render_log_panel(self) -> Panel | Text:
        with self._log_lock:
            lines = list(self._log_buffer)
        if not lines:
            return Text("")
        return Panel("\n".join(lines), title="Log", border_style="dim")

    def _render_layout(self) -> Layout:
        layout = Layout()
        log_renderable = self._render_log_panel()
        has_log = not (isinstance(log_renderable, Text) and log_renderable.plain == "")

        children: list[Layout] = [
            Layout(name="progress", renderable=self.progress),
            Layout(name="divider1", size=1, renderable=Rule(style="dim")),
            Layout(name="status", size=1, renderable=self._render_status()),
        ]
        if has_log:
            children.append(Layout(name="divider2", size=1, renderable=Rule(style="dim")))
            children.append(
                Layout(name="log", size=self._log_lines + 2, renderable=log_renderable)
            )

        layout.split_column(*children)
        return layout

    def _log_sink(self, msg: str) -> None:
        _, _, resolved = msg.partition(" | ")
        display = resolved.strip() if resolved else msg.strip()
        with self._log_lock:
            self._log_buffer.append(display)

    def _ensure_task(self, stage: str, *, total: int | None = None) -> TaskID:
        task_id = self.tasks_by_stage.get(stage)
        if task_id is not None:
            if total is not None:
                self.progress.update(task_id, total=total)
            return task_id
        task_id = self.progress.add_task(stage, total=total)
        self.tasks_by_stage[stage] = task_id
        return task_id

    def _complete_task(self, stage: str) -> None:
        task_id = self.tasks_by_stage.get(stage)
        if task_id is None:
            return
        task = self.progress.tasks[task_id]
        if task.total is None:
            total = max(int(task.completed), 1)
            self.progress.update(task_id, total=total, completed=total)
            return
        total = int(task.total)
        self.progress.update(task_id, completed=total)

    def _on_event(self, event: Event) -> None:
        if classify_event_level(event) > self._level:
            return
        event_type = event.event_type
        payload = event.payload or {}

        if event_type in {"validation_failed", "risk_detected"} or event_type.endswith(".validation_failed"):
            self.warning_count += 1
        if event_type.endswith("_skipped") or event_type.endswith(".chapter_skipped"):
            self.skip_count += 1
        if event_type.endswith("_retry") or event_type.endswith(".retry"):
            self.retry_count += 1
        if event_type.endswith(".artifact_written"):
            self.artifact_count += 1

        if event_type.endswith(".started"):
            stage = event_type.removesuffix(".started")
            total = payload.get("total_chapters")
            self._ensure_task(stage, total=total if isinstance(total, int) else None)
            return
        if event_type.endswith("_started") and "." not in event_type:
            self._ensure_task(event_type.removesuffix("_started"))
            return

        if event_type.endswith(".completed"):
            self._complete_task(event_type.removesuffix(".completed"))
            return
        if event_type.endswith("_completed") and "." not in event_type:
            self._complete_task(event_type.removesuffix("_completed"))
            return
        if event_type.endswith(".failed"):
            self._complete_task(event_type.removesuffix(".failed"))
            return
        if event_type.endswith("_failed") and "." not in event_type:
            self._complete_task(event_type.removesuffix("_failed"))
            return

        if event_type.endswith(".chapter_completed"):
            stage = event_type.removesuffix(".chapter_completed")
            self.progress.advance(self._ensure_task(stage), 1)
            return
        if event_type.endswith(".paragraph_completed"):
            stage = event_type.removesuffix(".paragraph_completed")
            self.progress.advance(self._ensure_task(stage), 1)
