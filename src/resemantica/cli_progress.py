from __future__ import annotations

import shutil
from collections import deque
from datetime import datetime
from threading import Lock
from time import monotonic
from types import TracebackType
from typing import Any

from rich.console import Console, ConsoleRenderable, Group, RichCast
from rich.highlighter import ReprHighlighter
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
        self._placeholder_task_id: TaskID | None = None
        self._started_at: datetime | None = None
        self._started_monotonic: float | None = None

    def _progress(self) -> Progress:
        if self.progress is None:
            raise RuntimeError("CLI progress has not been started")
        return self.progress

    def __enter__(self) -> CliProgressSubscriber:
        self.event_bus.subscribe("*", self._on_event)
        self._started_at = datetime.now().astimezone()
        self._started_monotonic = monotonic()

        if self._injected_progress:
            self.progress = self._injected_progress
            self.progress.start()
        else:
            self.progress = Progress(
                SpinnerColumn(),
                TextColumn("[cyan]{task.description}[/cyan]"),
                BarColumn(complete_style="green", finished_style="blue"),
                TaskProgressColumn(show_speed=False),
            )
            self._placeholder_task_id = self._progress().add_task("running...", total=None)
            _width = max(shutil.get_terminal_size().columns, 100)
            self._live = Live(
                get_renderable=self._render_layout,
                console=Console(stderr=True, width=_width),
                refresh_per_second=10,
                vertical_overflow="visible",
            )
            self._live.__enter__()
            replace_stderr_sink(self._log_sink, fmt="{message}")

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.event_bus.unsubscribe("*", self._on_event)

        if self._injected_progress:
            self._progress().stop()
        else:
            if self._live is not None:
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
            pairs.append(f"[yellow]skip: {self.skip_count}[/yellow]")
        if self.warning_count:
            pairs.append(f"[red]warn: {self.warning_count}[/red]")
        if self.retry_count:
            pairs.append(f"[magenta]retry: {self.retry_count}[/magenta]")
        if self.artifact_count:
            pairs.append(f"[cyan]artifacts: {self.artifact_count}[/cyan]")
        if not pairs:
            return Text("")
        return Text.from_markup("  |  ".join(pairs))

    def _render_log_panel(self) -> Panel | Text:
        with self._log_lock:
            lines = list(self._log_buffer)
        if not lines:
            return Text("")

        highlighter = ReprHighlighter()
        text = highlighter(Text("\n".join(lines)))
        return Panel(text, title="Log", border_style="dim")

    def _format_elapsed(self) -> str:
        if self._started_monotonic is None:
            return "0:00:00"
        elapsed_seconds = max(int(monotonic() - self._started_monotonic), 0)
        hours, remainder = divmod(elapsed_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"

    def _render_time_header(self) -> Text:
        started = self._started_at.isoformat(timespec="seconds") if self._started_at else "unknown"
        return Text.from_markup(
            f"[bold]Time started:[/bold] {started}\n"
            f"[bold]Elapsed Time:[/bold] {self._format_elapsed()}"
        )

    def _render_layout(self) -> Group:
        components: list[ConsoleRenderable | RichCast | str] = [
            self._render_time_header(),
            Rule(style="dim"),
            self._progress(),
            Rule(style="dim"),
            self._render_status(),
        ]
        log_panel = self._render_log_panel()
        has_log = not (isinstance(log_panel, Text) and log_panel.plain == "")
        if has_log:
            components.append(Rule(style="dim"))
            components.append(log_panel)
        return Group(*components)

    def _log_sink(self, msg: Any) -> None:
        text = str(msg)
        _, _, resolved = text.partition(" | ")
        display = resolved.strip() if resolved else text.strip()
        with self._log_lock:
            self._log_buffer.append(display)

    def _ensure_task(self, stage: str, *, total: int | None = None) -> TaskID:
        task_id = self.tasks_by_stage.get(stage)
        if task_id is not None:
            if total is not None:
                self._progress().update(task_id, total=total)
            return task_id

        placeholder = getattr(self, "_placeholder_task_id", None)
        if placeholder is not None:
            try:
                self._progress().remove_task(placeholder)
            except Exception:
                pass
            self._placeholder_task_id = None

        task_id = self._progress().add_task(stage, total=total)
        self.tasks_by_stage[stage] = task_id
        return task_id

    def _complete_task(self, stage: str) -> None:
        task_id = self.tasks_by_stage.get(stage)
        if task_id is None:
            return
        task = next((t for t in self._progress().tasks if t.id == task_id), None)
        if task is None:
            return
        if task.total is None:
            total = max(int(task.completed), 1)
            self._progress().update(task_id, total=total, completed=total)
            return
        total = int(task.total)
        self._progress().update(task_id, completed=total)

    def _on_event(self, event: Event) -> None:
        if classify_event_level(event) > self._level:
            return
        event_type = event.event_type
        payload = event.payload or {}

        if event_type.endswith(".validation_failed") or event_type.endswith(".risk_detected"):
            self.warning_count += 1
        if event_type.endswith(".chapter_skipped") or event_type.endswith(".paragraph_skipped"):
            self.skip_count += 1
        if event_type.endswith(".retry"):
            self.retry_count += 1
        if event_type.endswith(".artifact_written"):
            self.artifact_count += 1

        if event_type.endswith(".started"):
            stage = event_type.removesuffix(".started")
            total = payload.get("total_chapters")
            self._ensure_task(stage, total=total if isinstance(total, int) else None)
            return

        if event_type.endswith(".completed"):
            self._complete_task(event_type.removesuffix(".completed"))
            return
        if event_type.endswith(".failed"):
            self._complete_task(event_type.removesuffix(".failed"))
            return

        if event_type.endswith(".chapter_completed"):
            stage = event_type.removesuffix(".chapter_completed")
            self._progress().advance(self._ensure_task(stage), 1)
            return
        if event_type.endswith(".paragraph_completed"):
            stage = event_type.removesuffix(".paragraph_completed")
            self._progress().advance(self._ensure_task(stage), 1)
