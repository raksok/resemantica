from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.widgets import DataTable, Static

from resemantica.observability.adapter import LiveAdapter, NullAdapter, ObservabilityAdapter, PollAdapter
from resemantica.tracking.models import Event
from resemantica.tui.observability import (
    ObservabilityCounters,
    ObservabilitySeverityFilter,
    ObservabilitySnapshot,
    ObservabilitySourceFilter,
    ObservabilityVerbosity,
    apply_record_filters,
    available_chapter_filters,
    available_stage_filters,
    format_record,
    load_log_records,
)
from resemantica.tui.observability import (
    build_snapshot as build_obs_snapshot,
)
from resemantica.tui.screens.base import BaseScreen


class ObservabilityScreen(BaseScreen):
    BINDINGS = [
        Binding("v", "cycle_verbosity", "Verbose"),
        Binding("s", "cycle_source", "Source"),
        Binding("e", "cycle_severity", "Severity"),
        Binding("f", "cycle_stage_filter", "Stage"),
        Binding("c", "cycle_chapter_filter", "Chapter"),
        Binding("r", "refresh_observability", "Refresh"),
    ]

    def _content_widgets(self) -> ComposeResult:
        with Container(id="observability-content"):
            with VerticalScroll(id="observability-top"):
                yield Static("Observability", classes="app-title")
                yield Static("", id="observability-counters")
                yield Static("", id="observability-latest-failure")
                yield Static("", id="observability-filters")
                yield Static("", id="observability-live")
                yield Static("", id="observability-persisted")
                yield Static("", id="observability-logs")
            with Vertical(id="observability-bottom"):
                yield Static("Warnings & Failures", id="observability-warnings-header", classes="section-title")
                yield DataTable(id="observability-warnings-table")

    def on_mount(self) -> None:
        self._adapter: ObservabilityAdapter | None = None
        self._adapter_events: list[Event] = []
        self._verbosity: ObservabilityVerbosity = "normal"
        self._source_filter: ObservabilitySourceFilter = "all"
        self._severity_filter: ObservabilitySeverityFilter = "warnings/errors"
        self._stage_filter: str | None = None
        self._chapter_filter: int | None = None
        self._obs_snapshot = ObservabilitySnapshot(
            counters=ObservabilityCounters(),
            latest_failure=None,
            live_records=[],
            persisted_records=[],
            log_records=[],
        )
        table = self.query_one("#observability-warnings-table", DataTable)
        table.add_columns("Severity", "Event", "Message")
        super().on_mount()

    def on_unmount(self) -> None:
        if self._adapter is not None:
            self._adapter.close()
            self._adapter = None

    def _ensure_adapter(self) -> ObservabilityAdapter:
        if self._adapter is not None:
            return self._adapter

        active = getattr(self.app, "active_action", None)
        if active is not None:
            adapter: ObservabilityAdapter = LiveAdapter()
        else:
            rid = self._get_release_id()
            rn = self._get_run_id()
            if rid and rn:
                adapter = PollAdapter(release_id=rid, run_id=rn)
            else:
                adapter = NullAdapter()

        self._adapter = adapter
        self._adapter.subscribe(0, self._on_adapter_event)
        return self._adapter

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_observability()

    def _on_adapter_event(self, event: Event) -> None:
        if event.release_id != self._get_release_id() or event.run_id != self._get_run_id():
            return
        self._adapter_events.insert(0, event)
        self._adapter_events = self._adapter_events[:100]
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
        choices = [None, *available_stage_filters(self._obs_snapshot)]
        self._stage_filter = self._cycle(choices, self._stage_filter)
        self._refresh_observability()

    def action_cycle_chapter_filter(self) -> None:
        choices = [None, *available_chapter_filters(self._obs_snapshot)]
        self._chapter_filter = self._cycle(choices, self._chapter_filter)
        self._refresh_observability()

    def action_refresh_observability(self) -> None:
        self._refresh_observability()

    def _refresh_observability(self) -> None:
        adapter = self._ensure_adapter()
        persisted_events = self._load_recent_run_events(limit=100)
        log_path = self._log_path()
        log_records = load_log_records(log_path, limit=100) if log_path is not None else []
        live_events = self._adapter_events if isinstance(adapter, LiveAdapter) else []
        self._obs_snapshot = build_obs_snapshot(
            live_events=live_events,
            persisted_events=persisted_events,
            log_records=log_records,
        )
        self._render_observability()
        self._render_warnings()

    def _render_observability(self) -> None:
        counters = self.query_one("#observability-counters", Static)
        latest_failure = self.query_one("#observability-latest-failure", Static)
        filters = self.query_one("#observability-filters", Static)
        live_target = self.query_one("#observability-live", Static)
        persisted_target = self.query_one("#observability-persisted", Static)
        logs_target = self.query_one("#observability-logs", Static)

        summary = self._obs_snapshot.counters
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

        failure = self._obs_snapshot.latest_failure
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
                    "",
                    "[dim]v[/]=Verbose  [dim]s[/]=Source  [dim]e[/]=Severity  "
                    "[dim]f[/]=Stage  [dim]c[/]=Chapter  [dim]r[/]=Refresh",
                ]
            )
        )

        live_target.update(
            self._render_section(
                "Live Events",
                self._obs_snapshot.live_records,
                selected_source="live",
                empty_text="[dim]No live events yet.[/]",
            )
        )
        persisted_target.update(
            self._render_section(
                "Persisted Events",
                self._obs_snapshot.persisted_records,
                selected_source="persisted",
                empty_text=self._persisted_empty_text(),
            )
        )
        logs_target.update(
            self._render_section(
                "Logs",
                self._obs_snapshot.log_records,
                selected_source="logs",
                empty_text=self._log_empty_text(),
            )
        )

    def _render_section(
        self,
        title: str,
        records: list,
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
        formatted = [format_record(record, verbosity=self._verbosity) for record in filtered[:limit]]
        return f"[bold]{title}[/bold]\n" + "\n".join(formatted)

    def _render_warnings(self) -> None:
        table = self.query_one("#observability-warnings-table", DataTable)
        table.clear()

        release_id = self._get_release_id()
        if not release_id:
            table.add_row("--", "--", "No release selected")
            return

        events = self._load_recent_run_events(limit=50)
        for ev in events:
            table.add_row(
                ev.severity.upper(),
                ev.event_type,
                ev.message[:60],
            )

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
    def _cycle(options: tuple[Any, ...] | list[Any], current: Any) -> Any:
        if not options:
            return current
        try:
            index = options.index(current)
        except ValueError:
            return options[0]
        return options[(index + 1) % len(options)]
