from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest

from resemantica.orchestration.models import (
    StageResult,
    legal_transition,
    next_stage,
    STAGE_ORDER,
)
from resemantica.orchestration import emit_event, run_stage, resume_run, plan_cleanup, apply_cleanup
from resemantica.tracking.models import Event, RunState
from resemantica.tracking.repo import (
    get_tracking_db_path,
    ensure_tracking_db,
    save_event,
    load_events,
)


def _make_run_state(release_id: str, run_id: str, stage: str) -> Any:
    conn = ensure_tracking_db(release_id)
    try:
        from resemantica.tracking.repo import save_run_state
        state = RunState(run_id=run_id, release_id=release_id, stage_name=stage, status="running")
        save_run_state(conn, state)
        return state
    finally:
        conn.close()


class TestStageTransitions:
    def test_legal_forward_transition(self):
        assert legal_transition("preprocess-glossary", "preprocess-summaries") is True

    def test_legal_same_stage(self):
        assert legal_transition("preprocess-glossary", "preprocess-glossary") is True

    def test_legal_none_current(self):
        assert legal_transition(None, "preprocess-glossary") is True

    def test_illegal_backward_transition(self):
        assert legal_transition("preprocess-summaries", "preprocess-glossary") is False

    def test_next_stage(self):
        assert next_stage("preprocess-glossary") == "preprocess-summaries"
        assert next_stage("epub-rebuild") is None

    def test_stage_order_valid(self):
        assert len(STAGE_ORDER) > 0
        assert STAGE_ORDER[0] == "preprocess-glossary"
        assert STAGE_ORDER[-1] == "epub-rebuild"


class TestEventEmission:
    def test_emit_event_creates_event(self, tmp_path: Path):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        event = emit_event(
            run_id, release_id, "test.event",
            "test-stage", severity="info", message="test message"
        )

        assert event.event_type == "test.event"
        assert event.run_id == run_id
        assert event.release_id == release_id
        assert event.stage_name == "test-stage"
        assert event.severity == "info"
        assert event.message == "test message"

        conn = ensure_tracking_db(release_id)
        try:
            events = load_events(conn, run_id=run_id)
            assert len(events) == 1
            assert events[0].event_type == "test.event"
        finally:
            conn.close()

    def test_event_has_required_fields(self):
        event = Event(event_type="test", run_id="run1", release_id="rel1", stage_name="stage1")
        assert event.event_id != ""
        assert event.event_time != ""
        assert event.schema_version == "1.0"


class TestCleanupPlanApply:
    def test_plan_cleanup_creates_plan(self, tmp_path: Path):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        plan = plan_cleanup(release_id, run_id, scope="run", dry_run=True)

        assert plan["release_id"] == release_id
        assert plan["run_id"] == run_id
        assert plan["scope"] == "run"
        assert plan["dry_run"] is True
        assert "deletable_artifacts" in plan

        plan_path = get_tracking_db_path(release_id).parent / "cleanup_plan.json"
        assert plan_path.exists()

    def test_apply_without_plan_fails(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        result = apply_cleanup(release_id, run_id, scope="run")
        assert result["success"] is False

    def test_plan_then_apply_succeeds(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        plan = plan_cleanup(release_id, run_id, scope="run", dry_run=True)
        assert "deletable_artifacts" in plan

        result = apply_cleanup(release_id, run_id, scope="run")
        assert "deleted_files" in result


class TestResume:
    def test_resume_with_no_state_fails(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        result = resume_run(release_id, run_id)
        assert result.success is False
        assert "No checkpoint found" in result.message

    def test_resume_with_invalid_stage_fails(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        _make_run_state(release_id, run_id, "invalid-stage")

        result = resume_run(release_id, run_id, from_stage="invalid-stage")
        assert result.success is False


class TestRunStage:
    def test_run_unknown_stage_fails(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        result = run_stage(release_id, run_id, "unknown-stage")
        assert result.success is False
        assert "Unknown stage" in result.message

    def test_run_stage_illegal_transition(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        _make_run_state(release_id, run_id, "preprocess-summaries")

        result = run_stage(release_id, run_id, "preprocess-glossary")
        assert result.success is False
        assert "Illegal stage transition" in result.message
