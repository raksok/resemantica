from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any


def _iso(hour: int, minute: int, second: int = 0) -> str:
    return datetime(2026, 4, 24, hour, minute, second, tzinfo=timezone.utc).isoformat()


def _make_event(
    *,
    event_type: str,
    event_time: str,
    severity: str = "info",
    message: str = "",
    chapter_number: int | None = None,
    block_id: str | None = None,
    payload: dict[str, Any] | None = None,
):
    from resemantica.tracking.models import Event

    return Event(
        event_type=event_type,
        event_time=event_time,
        run_id="run-1",
        release_id="rel-1",
        stage_name="translate-chapter",
        chapter_number=chapter_number,
        block_id=block_id,
        severity=severity,
        message=message,
        payload=payload or {},
    )


def _make_log_line(
    *,
    time_value: str,
    level: str,
    message: str,
    logger_name: str = "resemantica.translation.pipeline",
    extra: dict[str, object] | None = None,
) -> str:
    return json.dumps(
        {
            "text": message,
            "record": {
                "time": {"repr": time_value},
                "level": {"name": level},
                "name": logger_name,
                "message": message,
                "extra": extra or {},
                "function": "test_fn",
                "line": 42,
                "file": {"name": "pipeline.py"},
            },
        }
    )


def _static_text(widget) -> str:
    return str(widget.content)


def test_parse_loguru_jsonl_line_extracts_record():
    from resemantica.tui.observability import parse_loguru_jsonl_line

    record = parse_loguru_jsonl_line(
        _make_log_line(
            time_value=_iso(12, 3),
            level="WARNING",
            message="Retrying chapter",
            extra={
                "stage_name": "translate-chapter",
                "chapter_number": 3,
                "block_id": "b-3",
                "event_type": "paragraph_retry",
            },
        )
    )

    assert record is not None
    assert record.source == "log"
    assert record.severity == "warning"
    assert record.event_type == "paragraph_retry"
    assert record.stage_name == "translate-chapter"
    assert record.chapter_number == 3
    assert record.block_id == "b-3"


def test_observability_counters_build_from_events_and_logs():
    from resemantica.tui.observability import build_counters, event_to_record, parse_loguru_jsonl_line

    log_record = parse_loguru_jsonl_line(
        _make_log_line(
            time_value=_iso(12, 5),
            level="WARNING",
            message="Retrying paragraph",
            extra={"event_type": "paragraph_retry"},
        )
    )
    assert log_record is not None

    counters = build_counters(
        [
            event_to_record(
                _make_event(
                    event_type="risk_detected",
                    event_time=_iso(12, 1),
                    severity="warning",
                    message="Risk raised",
                ),
                source="persisted",
            ),
            event_to_record(
                _make_event(
                    event_type="chapter_skipped",
                    event_time=_iso(12, 2),
                    message="Skipped",
                ),
                source="persisted",
            ),
            event_to_record(
                _make_event(
                    event_type="artifact_written",
                    event_time=_iso(12, 3),
                    message="Artifact written",
                ),
                source="live",
            ),
            event_to_record(
                _make_event(
                    event_type="stage_failed",
                    event_time=_iso(12, 4),
                    severity="error",
                    message="Stage failed",
                ),
                source="persisted",
            ),
            log_record,
        ]
    )

    assert counters.warnings == 2
    assert counters.failures == 1
    assert counters.skips == 1
    assert counters.retries == 1
    assert counters.artifacts == 1


def test_format_record_escapes_truncated_debug_metadata_for_textual_static():
    from textual.widgets import Static

    from resemantica.tui.observability import ObservabilityRecord, format_record

    record = ObservabilityRecord(
        source="persisted",
        timestamp=_iso(12, 1),
        severity="info",
        stage_name="packets-build",
        event_type="stage_completed",
        logger_name=None,
        message="Packets: 0 built, 0 up-to-date, 8 skipped, 0 failed",
        chapter_number=None,
        block_id=None,
        metadata={"results": [{"bundle_path": "x" * 500}]},
    )

    Static().update("[bold]Persisted Events[/bold]\n" + format_record(record, verbosity="debug"))


def test_latest_failure_prefers_newest_record():
    from resemantica.tui.observability import event_to_record, parse_loguru_jsonl_line, select_latest_failure

    log_record = parse_loguru_jsonl_line(
        _make_log_line(
            time_value=_iso(12, 7),
            level="ERROR",
            message="Newest failure",
        )
    )
    assert log_record is not None

    latest = select_latest_failure(
        [
            event_to_record(
                _make_event(
                    event_type="chapter_failed",
                    event_time=_iso(12, 1),
                    severity="error",
                    message="Older failure",
                ),
                source="persisted",
            ),
            log_record,
        ]
    )

    assert latest is not None
    assert latest.message == "Newest failure"


def test_record_filters_apply_verbosity_stage_and_chapter():
    from resemantica.tui.observability import apply_record_filters, event_to_record, parse_loguru_jsonl_line

    info_record = event_to_record(
        _make_event(
            event_type="chapter_completed",
            event_time=_iso(12, 1),
            severity="info",
            message="Info event",
            chapter_number=2,
        ),
        source="persisted",
    )
    warning_record = event_to_record(
        _make_event(
            event_type="risk_detected",
            event_time=_iso(12, 2),
            severity="warning",
            message="Warning event",
            chapter_number=2,
        ),
        source="persisted",
    )
    debug_record = parse_loguru_jsonl_line(
        _make_log_line(
            time_value=_iso(12, 3),
            level="DEBUG",
            message="Debug log",
            extra={"stage_name": "translate-chapter", "chapter_number": 2},
        )
    )
    assert debug_record is not None

    normal = apply_record_filters(
        [info_record, warning_record, debug_record],
        verbosity="normal",
        severity_filter="all",
        stage_filter="translate-chapter",
        chapter_filter=2,
    )
    verbose = apply_record_filters(
        [info_record, warning_record, debug_record],
        verbosity="verbose",
        severity_filter="all",
        stage_filter="translate-chapter",
        chapter_filter=2,
    )
    debug = apply_record_filters(
        [info_record, warning_record, debug_record],
        verbosity="debug",
        severity_filter="all",
        stage_filter="translate-chapter",
        chapter_filter=2,
    )

    assert [record.message for record in normal] == ["Info event"]
    assert [record.message for record in verbose] == ["Info event"]
    assert [record.message for record in debug] == ["Info event", "Warning event", "Debug log"]


def test_load_log_records_missing_path_returns_empty(tmp_path):
    from resemantica.tui.observability import load_log_records

    records = load_log_records(tmp_path / "missing.jsonl")

    assert records == []


def test_load_log_records_ignores_malformed_lines(tmp_path):
    from resemantica.tui.observability import load_log_records

    path = tmp_path / "run-1.jsonl"
    path.write_text(
        "\n".join(
            [
                "not-json",
                _make_log_line(time_value=_iso(12, 1), level="INFO", message="kept"),
            ]
        ),
        encoding="utf-8",
    )

    records = load_log_records(path)

    assert [record.message for record in records] == ["kept"]


def test_tui_observability_screen_mounts_without_release():
    from textual.widgets import Static

    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test() as pilot:
            await pilot.press("5")
            await pilot.pause()

            counters = pilot.app.screen.query_one("#observability-counters", Static)
            persisted = pilot.app.screen.query_one("#observability-persisted", Static)
            logs = pilot.app.screen.query_one("#observability-logs", Static)

            assert "Warnings 0" in _static_text(counters)
            assert "No release/run selected." in _static_text(persisted)
            assert "No release/run selected." in _static_text(logs)

    asyncio.run(run())


def test_tui_observability_screen_renders_persisted_events(monkeypatch, tmp_path):
    from textual.widgets import Static

    from resemantica.tui.app import ResemanticaApp

    class _Conn:
        def close(self) -> None:
            pass

    def fake_ensure_tracking_db(release_id: str):
        assert release_id == "rel-1"
        return _Conn()

    def fake_load_events(conn, run_id=None, release_id=None, limit=100):
        assert run_id == "run-1"
        assert release_id == "rel-1"
        return [
            _make_event(
                event_type="risk_detected",
                event_time=_iso(12, 1),
                severity="warning",
                message="Persisted warning",
                chapter_number=4,
            )
        ]

    monkeypatch.setattr("resemantica.tracking.repo.ensure_tracking_db", fake_ensure_tracking_db)
    monkeypatch.setattr("resemantica.tracking.repo.load_events", fake_load_events)
    monkeypatch.setattr(
        "resemantica.tui.screens.observability.ObservabilityScreen._log_path",
        lambda self: tmp_path / "missing.jsonl",
    )

    async def run() -> None:
        app = ResemanticaApp(release_id="rel-1", run_id="run-1")
        async with app.run_test() as pilot:
            await pilot.press("5")
            await pilot.pause()

            persisted = pilot.app.screen.query_one("#observability-persisted", Static)

            assert "Persisted warning" in _static_text(persisted)
            assert "ch=4" in _static_text(persisted)

    asyncio.run(run())


def test_tui_observability_screen_shows_live_event(monkeypatch, tmp_path):
    from textual.widgets import Static

    from resemantica.orchestration.events import emit_event
    from resemantica.tui.app import ResemanticaApp

    class _Conn:
        def close(self) -> None:
            pass

    monkeypatch.setattr("resemantica.tracking.repo.ensure_tracking_db", lambda release_id: _Conn())
    monkeypatch.setattr("resemantica.tracking.repo.load_events", lambda conn, **kwargs: [])
    monkeypatch.setattr("resemantica.orchestration.events.ensure_tracking_db", lambda release_id: _Conn())
    monkeypatch.setattr("resemantica.orchestration.events.save_event", lambda conn, event: None)
    monkeypatch.setattr(
        "resemantica.tui.screens.observability.ObservabilityScreen._log_path",
        lambda self: tmp_path / "missing.jsonl",
    )

    async def run() -> None:
        app = ResemanticaApp(release_id="rel-1", run_id="run-1")
        async with app.run_test() as pilot:
            app.active_action = "test-action"
            await pilot.press("5")
            await pilot.pause()

            emit_event(
                "run-1",
                "rel-1",
                "risk_detected",
                "translate-chapter",
                severity="warning",
                message="Live warning",
                chapter_number=2,
            )
            await pilot.pause()
            await pilot.pause()

            screen = pilot.app.screen
            screen._refresh_observability()
            await pilot.pause()

            live = pilot.app.screen.query_one("#observability-live", Static)
            assert "Live warning" in _static_text(live)
            assert "ch=2" in _static_text(live)

    asyncio.run(run())
