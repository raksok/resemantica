from __future__ import annotations

from datetime import datetime
from io import StringIO
from time import monotonic

from rich.console import Console
from rich.progress import Progress

from resemantica.cli_progress import CliProgressSubscriber
from resemantica.orchestration.events import EventBus
from resemantica.tracking.models import Event


def _progress() -> Progress:
    return Progress(console=Console(file=StringIO(), force_terminal=False), auto_refresh=False)


def test_cli_progress_subscribes_and_unsubscribes() -> None:
    bus = EventBus()
    subscriber = CliProgressSubscriber(event_bus=bus, progress=_progress())

    with subscriber:
        assert subscriber._on_event in bus._subscribers["*"]

    assert subscriber._on_event not in bus._subscribers["*"]


def test_cli_progress_creates_and_advances_chapter_task() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=4)

    subscriber._on_event(
        Event(
            event_type="preprocess-summaries.started",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-summaries",
            payload={"total_chapters": 2},
        )
    )
    subscriber._on_event(
        Event(
            event_type="preprocess-summaries.chapter_completed",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-summaries",
            chapter_number=1,
        )
    )

    task_id = subscriber.tasks_by_stage["preprocess-summaries"]
    task = subscriber.progress.tasks[task_id]
    assert task.total == 2
    assert task.completed == 1


def test_cli_progress_updates_generic_progress_task() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=4)

    subscriber._on_event(
        Event(
            event_type="preprocess-glossary.discover.scoring.progress",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-glossary",
            payload={"processed_count": 40, "total_count": 100, "phase": "c_value"},
        )
    )

    task_id = subscriber.tasks_by_stage["preprocess-glossary.discover.scoring"]
    task = subscriber.progress.tasks[task_id]
    assert task.total == 100
    assert task.completed == 40


def test_cli_progress_formats_graph_extract_progress_log_line() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=4)

    subscriber._on_event(
        Event(
            event_type="preprocess-graph.extract.progress",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-graph",
            chapter_number=12,
            payload={
                "chapter_index": 3,
                "total_count": 10,
                "cache_hit": True,
                "chapter_entity_count": 4,
                "chapter_relationship_count": 2,
                "chapter_deferred_count": 1,
                "processed_count": 3,
            },
        )
    )

    assert list(subscriber._log_buffer) == [
        "Graph extract 3/10 chapter=12: cache=hit, entities=4, relationships=2, deferred=1"
    ]
    task_id = subscriber.tasks_by_stage["preprocess-graph.extract"]
    task = subscriber.progress.tasks[task_id]
    assert task.total == 10
    assert task.completed == 3


def test_cli_progress_formats_graph_resume_and_artifact_logs() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=4)

    subscriber._on_event(
        Event(
            event_type="preprocess-graph.extract.resume_summary",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-graph",
            payload={
                "reusable_draft_count": 7,
                "stale_draft_count": 1,
                "missing_draft_count": 2,
                "forced_rebuild_count": 0,
            },
        )
    )
    subscriber._on_event(
        Event(
            event_type="preprocess-graph.snapshot.artifact_written",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-graph",
            payload={
                "artifact_path": "artifacts/releases/rel/graph/snapshot.json",
                "entity_count": 12,
                "relationship_count": 5,
            },
        )
    )

    assert list(subscriber._log_buffer) == [
        "Graph resume: reusable=7, stale=1, missing=2",
        "Graph artifact written: artifacts/releases/rel/graph/snapshot.json (entities=12, relationships=5)",
    ]
    assert subscriber.artifact_count == 1


def test_cli_progress_logs_model_payload_details_without_new_events() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=1)

    subscriber._on_event(
        Event(
            event_type="preprocess-idioms.fill.model_started",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-idioms",
            message="Idiom filler model filler-a started: 12 renderings",
            payload={
                "model_name": "filler-a",
                "candidate_count": 12,
                "skipped_count": 3,
                "vote_kind": "rendering",
            },
        )
    )

    lines = list(subscriber._log_buffer)
    assert len(lines) == 1
    assert lines[0] == (
        "Idiom filler model filler-a started: 12 renderings "
        "(candidates=12, skipped=3, vote=rendering)"
    )


def test_cli_progress_counts_warnings_and_skips() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=4)

    subscriber._on_event(
        Event(
            event_type="preprocess-summaries.started",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-summaries",
        )
    )
    subscriber._on_event(
        Event(
            event_type="preprocess-summaries.validation_failed",
            run_id="run",
            release_id="rel",
            stage_name="validation",
        )
    )
    subscriber._on_event(
        Event(
            event_type="preprocess-summaries.chapter_skipped",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-summaries",
        )
    )

    assert subscriber.warning_count == 1
    assert subscriber.skip_count == 1


def test_cli_progress_counts_review_promote_artifacts() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=4)

    for event_type in (
        "preprocess-glossary.review.json.artifact_written",
        "preprocess-glossary.review.csv.artifact_written",
        "preprocess-idioms.promote.policies.artifact_written",
    ):
        subscriber._on_event(
            Event(
                event_type=event_type,
                run_id="run",
                release_id="rel",
                stage_name="preprocess",
            )
        )

    assert subscriber.artifact_count == 3


def test_cli_progress_completes_indeterminate_task() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=4)

    subscriber._on_event(
        Event(
            event_type="preprocess-glossary.promote.started",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-glossary",
        )
    )
    subscriber._on_event(
        Event(
            event_type="preprocess-glossary.promote.completed",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-glossary",
        )
    )

    task = subscriber.progress.tasks[subscriber.tasks_by_stage["preprocess-glossary.promote"]]
    assert task.finished
    assert task.total == 1
    assert task.completed == 1


def test_cli_progress_counter_text_is_global() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress())
    subscriber.warning_count = 1
    subscriber.skip_count = 2
    subscriber.retry_count = 3
    subscriber.artifact_count = 4

    assert subscriber._counter_text() == "warn 1 skip 2 retry 3 artifacts 4"


def test_cli_progress_layout_includes_timing_header() -> None:
    output = StringIO()
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress())
    subscriber.progress = _progress()
    subscriber._started_at = datetime(2026, 5, 15, 10, 30, 0).astimezone()
    subscriber._started_monotonic = monotonic() - 65

    Console(file=output, force_terminal=False, width=100).print(subscriber._render_layout())

    text = output.getvalue()
    assert "Time started:" in text
    assert "Elapsed Time:" in text
    assert "0:01:" in text


def test_cli_progress_filters_events_by_cli_verbosity() -> None:
    subscriber = CliProgressSubscriber(event_bus=EventBus(), progress=_progress(), verbosity=0)

    subscriber._on_event(
        Event(
            event_type="preprocess-summaries.chapter_completed",
            run_id="run",
            release_id="rel",
            stage_name="preprocess-summaries",
            chapter_number=1,
        )
    )

    assert subscriber.tasks_by_stage == {}
