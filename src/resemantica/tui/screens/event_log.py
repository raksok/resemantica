from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from resemantica.orchestration.events import subscribe, unsubscribe
from resemantica.tracking.models import Event
from resemantica.tui.observability import (
    ObservabilitySeverityFilter,
    ObservabilitySnapshot,
    ObservabilitySourceFilter,
    ObservabilityVerbosity,
    apply_record_filters,
    available_chapter_filters,
    available_stage_filters,
    build_snapshot,
    format_record,
    load_log_records,
)
from resemantica.tui.screens.base import BaseScreen


class EventLogScreen(BaseScreen):
    BINDINGS = [
        Binding("v", "cycle_verbosity", "Verbosity"),
        Binding("s", "cycle_source", "Source"),
        Binding("e", "cycle_severity", "Severity"),
        Binding("t", "cycle_stage_filter", "Stage"),
        Binding("c", "cycle_chapter_filter", "Chapter"),
        Binding("r", "refresh_observability", "Refresh"),
    ]

    def _content_widgets(self) -> ComposeResult:
        with VerticalScroll(id="event-log-content"):
            yield Static("Observability", classes="app-title")
            yield Static("", id="event-log-counters")
            yield Static("", id="event-log-latest-failure")
            yield Static("", id="event-log-filters")
            yield Static("", id="event-log-live")
            yield Static("", id="event-log-persisted")
            yield Static("", id="event-log-logs")

    def on_mount(self) -> None:
        self._events: list[Event] = []
        self._verbosity: ObservabilityVerbosity = "normal"
        self._source_filter: ObservabilitySourceFilter = "all"
        self._severity_filter: ObservabilitySeverityFilter = "warnings/errors"
        self._stage_filter: str | None = None
        self._chapter_filter: int | None = None
        self._snapshot = ObservabilitySnapshot(
            counters=build_snapshot(live_events=[], persisted_events=[], log_records=[]).counters,
            latest_failure=None,
            live_records=[],
            persisted_records=[],
            log_records=[],
        )
        subscribe("*", self._on_event)
        super().on_mount()

    def on_unmount(self) -> None:
        unsubscribe("*", self._on_event)

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_observability()

    def _on_event(self, event: Event) -> None:
        if event.release_id != self._get_release_id() or event.run_id != self._get_run_id():
            return
        self._events.insert(0, event)
        self._events = self._events[:100]
        try:
            self.app.call_from_thread(self._refresh_observability)
        except RuntimeError:
            self._refresh_observability()

    def action_cycle_verbosity(self) -> None:
        self._verbosity = self._cycle(("normal", "verbose", "debug"), self._verbosity)
        self._refresh_observability()

    def action_cycle_source(self) -> None:
        self._source_filter = self._cycle(("all", "live", "persisted", "logs"), self._source_filter)
        self._refresh_observability()

    def action_cycle_severity(self) -> None:
        self._severity_filter = self._cycle(("all", "warnings/errors", "errors"), self._severity_filter)
        self._refresh_observability()

    def action_cycle_stage_filter(self) -> None:
        choices = [None, *available_stage_filters(self._snapshot)]
        self._stage_filter = self._cycle(choices, self._stage_filter)
        self._refresh_observability()

    def action_cycle_chapter_filter(self) -> None:
        choices = [None, *available_chapter_filters(self._snapshot)]
        self._chapter_filter = self._cycle(choices, self._chapter_filter)
        self._refresh_observability()

    def action_refresh_observability(self) -> None:
        self._refresh_observability()

    def _refresh_observability(self) -> None:
        persisted_events = self._load_recent_run_events(limit=100)
        log_path = self._log_path()
        log_records = load_log_records(log_path, limit=100) if log_path is not None else []
        self._snapshot = build_snapshot(
            live_events=self._events,
            persisted_events=persisted_events,
            log_records=log_records,
        )
        self._render_observability()

    def _render_observability(self) -> None:
        counters = self.query_one("#event-log-counters", Static)
        latest_failure = self.query_one("#event-log-latest-failure", Static)
        filters = self.query_one("#event-log-filters", Static)
        live_target = self.query_one("#event-log-live", Static)
        persisted_target = self.query_one("#event-log-persisted", Static)
        logs_target = self.query_one("#event-log-logs", Static)

        summary = self._snapshot.counters
        counters.update(
            "\n".join(
                [
                    "[bold]Counters[/bold]",
                    (
                        f"Warnings {summary.warnings}   Failures {summary.failures}   "
                        f"Skips {summary.skips}   Retries {summary.retries}   "
                        f"Artifacts {summary.artifacts}"
                    ),
                ]
            )
        )

        failure = self._snapshot.latest_failure
        if failure is None:
            latest_failure.update("[bold]Latest Failure[/bold]\n[dim]No failures for this run.[/]")
        else:
            latest_failure.update(
                "[bold]Latest Failure[/bold]\n"
                + format_record(failure, verbosity="debug" if self._verbosity == "debug" else "verbose")
            )

        filters.update(
            "\n".join(
                [
                    "[bold]Filters[/bold]",
                    (
                        f"Verbosity: {self._verbosity}   Source: {self._source_filter}   "
                        f"Severity: {self._severity_filter}   "
                        f"Stage: {self._stage_filter or 'all'}   "
                        f"Chapter: {self._chapter_filter if self._chapter_filter is not None else 'all'}"
                    ),
                ]
            )
        )

        live_target.update(
            self._render_section(
                "Live Events",
                self._snapshot.live_records,
                selected_source="live",
                empty_text="[dim]No live events yet.[/]",
            )
        )
        persisted_target.update(
            self._render_section(
                "Persisted Events",
                self._snapshot.persisted_records,
                selected_source="persisted",
                empty_text=self._persisted_empty_text(),
            )
        )
        logs_target.update(
            self._render_section(
                "Logs",
                self._snapshot.log_records,
                selected_source="logs",
                empty_text=self._log_empty_text(),
            )
        )

    def _render_section(
        self,
        title: str,
        records,
        *,
        selected_source: ObservabilitySourceFilter,
        empty_text: str,
    ) -> str:
        if self._source_filter != "all" and self._source_filter != selected_source:
            return f"[bold]{title}[/bold]\n[dim]Filtered out by source.[/]"

        filtered = apply_record_filters(
            records,
            verbosity=self._verbosity,
            severity_filter=self._severity_filter,
            stage_filter=self._stage_filter,
            chapter_filter=self._chapter_filter,
        )
        if not filtered:
            return f"[bold]{title}[/bold]\n{empty_text}"

        limit = {"normal": 8, "verbose": 12, "debug": 20}[self._verbosity]
        lines = [format_record(record, verbosity=self._verbosity) for record in filtered[:limit]]
        return f"[bold]{title}[/bold]\n" + "\n".join(lines)

    def _persisted_empty_text(self) -> str:
        if not self._get_release_id() or not self._get_run_id():
            return "[dim]No release/run selected.[/]"
        return "[dim]No persisted events for this run yet.[/]"

    def _log_empty_text(self) -> str:
        run_id = self._get_run_id()
        if not self._get_release_id() or not run_id:
            return "[dim]No release/run selected.[/]"
        log_path = self._log_path()
        if log_path is None or not log_path.exists():
            return "[dim]No JSONL log file for this run yet.[/]"
        return "[dim]No log entries for this run yet.[/]"

    def _log_path(self) -> Path | None:
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if not release_id or not run_id:
            return None
        try:
            from resemantica.settings import derive_paths, load_config

            config = load_config(getattr(self.app, "config_path", None))
            paths = derive_paths(config, release_id=release_id)
            return paths.artifact_root / "logs" / f"{run_id}.jsonl"
        except Exception:
            return None

    @staticmethod
    def _cycle(options, current):
        if not options:
            return current
        try:
            index = options.index(current)
        except ValueError:
            return options[0]
        return options[(index + 1) % len(options)]
