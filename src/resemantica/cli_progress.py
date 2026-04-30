from __future__ import annotations

from typing import Any

from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TaskProgressColumn, TextColumn

from resemantica.orchestration.events import default_event_bus
from resemantica.tracking.models import Event


class CliProgressSubscriber:
    def __init__(self, *, event_bus: Any = default_event_bus, progress: Progress | None = None) -> None:
        self.event_bus = event_bus
        self.progress = progress or Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(show_speed=False),
            TextColumn("{task.fields[counters]}"),
        )
        self.tasks_by_stage: dict[str, TaskID] = {}
        self.warning_count = 0
        self.skip_count = 0
        self.retry_count = 0
        self.artifact_count = 0

    def __enter__(self) -> CliProgressSubscriber:
        self.event_bus.subscribe("*", self._on_event)
        self.progress.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.event_bus.unsubscribe("*", self._on_event)
        self.progress.stop()

    def _counter_text(self) -> str:
        parts: list[str] = []
        if self.warning_count:
            parts.append(f"warn {self.warning_count}")
        if self.skip_count:
            parts.append(f"skip {self.skip_count}")
        if self.retry_count:
            parts.append(f"retry {self.retry_count}")
        if self.artifact_count:
            parts.append(f"artifacts {self.artifact_count}")
        return " ".join(parts)

    def _update_counters(self) -> None:
        counters = self._counter_text()
        for task_id in self.tasks_by_stage.values():
            self.progress.update(task_id, counters=counters)

    def _ensure_task(self, stage: str, *, total: int | None = None) -> TaskID:
        task_id = self.tasks_by_stage.get(stage)
        if task_id is not None:
            if total is not None:
                self.progress.update(task_id, total=total)
            return task_id
        task_id = self.progress.add_task(stage, total=total, counters=self._counter_text())
        self.tasks_by_stage[stage] = task_id
        return task_id

    def _complete_task(self, stage: str) -> None:
        task_id = self.tasks_by_stage.get(stage)
        if task_id is None:
            return
        task = self.progress.tasks[task_id]
        total = task.total if task.total is not None else task.completed
        self.progress.update(task_id, completed=total)

    def _on_event(self, event: Event) -> None:
        event_type = event.event_type
        payload = event.payload or {}

        if event_type in {"validation_failed", "risk_detected"} or event_type.endswith(".validation_failed"):
            self.warning_count += 1
            self._update_counters()
        if event_type.endswith("_skipped") or event_type.endswith(".chapter_skipped"):
            self.skip_count += 1
            self._update_counters()
        if event_type.endswith("_retry") or event_type.endswith(".retry"):
            self.retry_count += 1
            self._update_counters()
        if event_type.endswith(".artifact_written"):
            self.artifact_count += 1
            self._update_counters()

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
