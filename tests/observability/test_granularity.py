from __future__ import annotations

from resemantica.observability.granularity import classify_event_level
from resemantica.tracking.models import Event


def _make_event(*, event_type: str, severity: str = "info") -> Event:
    return Event(
        event_type=event_type,
        run_id="run-1",
        release_id="rel-1",
        stage_name="test-stage",
        severity=severity,
    )


def test_classify_stage_level() -> None:
    assert classify_event_level(_make_event(event_type="stage_started")) == 1
    assert classify_event_level(_make_event(event_type="stage_completed")) == 1
    assert classify_event_level(_make_event(event_type="stage_failed")) == 1


def test_classify_dot_notation_stage() -> None:
    assert classify_event_level(_make_event(event_type="orchestration.stage_started")) == 1
    assert classify_event_level(_make_event(event_type="cleanup.plan_created")) == 1


def test_classify_chapter_level() -> None:
    assert classify_event_level(_make_event(event_type="chapter_started")) == 2
    assert classify_event_level(_make_event(event_type="chapter_completed")) == 2
    assert classify_event_level(_make_event(event_type="chapter_skipped")) == 2


def test_classify_namespaced_chapter() -> None:
    assert classify_event_level(_make_event(event_type="preprocess-glossary.discover.chapter_started")) == 2
    assert classify_event_level(_make_event(event_type="epub.extraction.chapter_completed")) == 2


def test_classify_paragraph_level() -> None:
    assert classify_event_level(_make_event(event_type="paragraph_started")) == 3
    assert classify_event_level(_make_event(event_type="paragraph_completed")) == 3
    assert classify_event_level(_make_event(event_type="paragraph_skipped")) == 3


def test_classify_token_level() -> None:
    assert classify_event_level(_make_event(event_type="risk_detected")) == 4
    assert classify_event_level(_make_event(event_type="term_found")) == 4
    assert classify_event_level(_make_event(event_type="entity_extracted")) == 4


def test_classify_error() -> None:
    event = _make_event(event_type="chapter_completed", severity="error")
    assert classify_event_level(event) == 0


def test_classify_unknown() -> None:
    assert classify_event_level(_make_event(event_type="some_unknown_type")) == 1


def test_classify_error_severity_overrides_type() -> None:
    event = _make_event(event_type="term_found", severity="error")
    assert classify_event_level(event) == 0
