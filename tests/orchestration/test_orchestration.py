from __future__ import annotations

from pathlib import Path
from typing import Any

from resemantica.orchestration import (
    OrchestrationRunner,
    apply_cleanup,
    emit_event,
    execute_retry_failed,
    plan_cleanup,
    plan_retry_failed,
    resume_run,
    run_stage,
)
from resemantica.orchestration.models import (
    STAGE_ORDER,
    legal_transition,
    next_stage,
)
from resemantica.orchestration.stop import StopToken
from resemantica.tracking.models import Event, RunState
from resemantica.tracking.repo import (
    ensure_tracking_db,
    get_tracking_db_path,
    load_events,
    load_run_state,
    save_run_state,
)


def _make_run_state(
    release_id: str,
    run_id: str,
    stage: str,
    *,
    status: str = "running",
    checkpoint: dict[str, Any] | None = None,
) -> Any:
    conn = ensure_tracking_db(release_id)
    try:
        state = RunState(
            run_id=run_id,
            release_id=release_id,
            stage_name=stage,
            status=status,
            checkpoint=checkpoint or {},
        )
        save_run_state(conn, state)
        return state
    finally:
        conn.close()


class TestStageTransitions:
    def test_legal_forward_transition(self):
        assert legal_transition("preprocess-summaries", "preprocess-glossary") is True

    def test_legal_same_stage(self):
        assert legal_transition("preprocess-glossary", "preprocess-glossary") is True

    def test_legal_none_current(self):
        assert legal_transition(None, "preprocess-summaries") is True

    def test_illegal_backward_transition(self):
        assert legal_transition("preprocess-glossary", "preprocess-summaries") is False

    def test_next_stage(self):
        assert next_stage("preprocess-summaries") == "preprocess-glossary"
        assert next_stage("epub-rebuild") is None

    def test_stage_order_valid(self):
        assert len(STAGE_ORDER) > 0
        assert STAGE_ORDER[0] == "preprocess-summaries"
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

        _make_run_state(release_id, run_id, "preprocess-glossary")

        result = run_stage(release_id, run_id, "preprocess-summaries")
        assert result.success is False
        assert "Illegal stage transition" in result.message

    def test_run_stage_allow_rewind_backward(self, monkeypatch):
        import uuid

        from resemantica.orchestration.models import StageResult

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        monkeypatch.setattr(
            OrchestrationRunner, "_execute_stage",
            lambda *a, **kw: StageResult(True, a[1], "mocked"),
        )

        _make_run_state(release_id, run_id, "preprocess-glossary")

        result = run_stage(release_id, run_id, "preprocess-summaries", allow_rewind=True)
        assert result.success is True

    def test_run_stage_allow_rewind_updates_state(self, monkeypatch):
        import uuid

        from resemantica.orchestration.models import StageResult

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        monkeypatch.setattr(
            OrchestrationRunner, "_execute_stage",
            lambda *a, **kw: StageResult(True, a[1], "mocked"),
        )

        _make_run_state(release_id, run_id, "preprocess-glossary")

        run_stage(release_id, run_id, "preprocess-summaries", allow_rewind=True)

        conn = ensure_tracking_db(release_id)
        try:
            state = load_run_state(conn, run_id)
            assert state is not None
            assert state.stage_name == "preprocess-summaries"
        finally:
            conn.close()

    def test_run_stage_allow_rewind_backward_default_false(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        _make_run_state(release_id, run_id, "preprocess-glossary")

        result = run_stage(release_id, run_id, "preprocess-summaries")
        assert result.success is False
        assert "Illegal stage transition" in result.message

    def test_runner_production_dry_run_returns_ordered_graph(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        result = OrchestrationRunner(release_id, run_id).run_production(dry_run=True)

        assert result.success is True
        assert [stage["stage_name"] for stage in result.metadata["stages"]] == STAGE_ORDER

    def test_runner_production_without_state_starts_at_summaries(self, monkeypatch):
        import uuid

        from resemantica.orchestration.models import StageResult

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"
        calls: list[tuple[str, dict[str, Any]]] = []

        def fake_run_stage(self, stage_name: str, **kwargs):
            calls.append((stage_name, kwargs))
            return StageResult(True, stage_name, "ok")

        monkeypatch.setattr(OrchestrationRunner, "run_stage", fake_run_stage)

        result = OrchestrationRunner(release_id, run_id).run_production()

        assert result.success is True
        assert calls[0][0] == "preprocess-summaries"

    def test_runner_production_retries_failed_stage_with_checkpoint_scope(self, monkeypatch):
        import uuid

        from resemantica.orchestration.models import StageResult

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"
        _make_run_state(
            release_id,
            run_id,
            "preprocess-graph",
            status="failed",
            checkpoint={"chapter_start": 11, "chapter_end": 14},
        )
        calls: list[tuple[str, dict[str, Any]]] = []

        def fake_run_stage(self, stage_name: str, **kwargs):
            calls.append((stage_name, kwargs))
            return StageResult(True, stage_name, "ok")

        monkeypatch.setattr(OrchestrationRunner, "run_stage", fake_run_stage)

        result = OrchestrationRunner(release_id, run_id).run_production()

        assert result.success is True
        assert calls[0][0] == "preprocess-graph"
        assert calls[0][1]["chapter_start"] == 11
        assert calls[0][1]["chapter_end"] == 14

    def test_runner_production_after_completed_stage_starts_at_next_stage(self, monkeypatch):
        import uuid

        from resemantica.orchestration.models import StageResult

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"
        _make_run_state(release_id, run_id, "preprocess-idioms", status="completed")
        calls: list[tuple[str, dict[str, Any]]] = []

        def fake_run_stage(self, stage_name: str, **kwargs):
            calls.append((stage_name, kwargs))
            return StageResult(True, stage_name, "ok")

        monkeypatch.setattr(OrchestrationRunner, "run_stage", fake_run_stage)

        result = OrchestrationRunner(release_id, run_id).run_production()

        assert result.success is True
        assert calls[0][0] == "preprocess-graph"

    def test_runner_production_force_starts_at_first_stage_and_forwards_force(self, monkeypatch):
        import uuid

        from resemantica.orchestration.models import StageResult

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"
        _make_run_state(release_id, run_id, "translate-range", status="completed")
        calls: list[tuple[str, dict[str, Any]]] = []

        def fake_run_stage(self, stage_name: str, **kwargs):
            calls.append((stage_name, kwargs))
            return StageResult(True, stage_name, "ok")

        monkeypatch.setattr(OrchestrationRunner, "run_stage", fake_run_stage)

        result = OrchestrationRunner(release_id, run_id).run_production(force=True)

        assert result.success is True
        assert calls[0][0] == "preprocess-summaries"
        assert all(call_kwargs["force"] is True for _, call_kwargs in calls)

    def test_translate_range_requires_bounds(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        result = OrchestrationRunner(release_id, run_id).run_stage("translate-range")

        assert result.success is False
        assert "No extracted chapters found" in result.message

    def test_translate_range_infers_bounds_from_extracted_chapters(self, monkeypatch):
        import uuid

        from resemantica.orchestration.models import StageResult
        from resemantica.settings import derive_paths, load_config

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"
        config = load_config()
        paths = derive_paths(config, release_id=release_id)
        paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
        (paths.extracted_chapters_dir / "chapter-2.json").write_text("{}")
        (paths.extracted_chapters_dir / "chapter-3.json").write_text("{}")

        translated = []

        def fake_translate_chapter(
            self,
            *,
            chapter_number: int,
            force: bool = False,
            stop_token=None,
            llm_client=None,
        ):
            translated.append(chapter_number)
            return StageResult(True, "translate-chapter", "ok")

        monkeypatch.setattr(OrchestrationRunner, "_translate_chapter", fake_translate_chapter)

        config.translation.batched_model_order = False
        result = OrchestrationRunner(release_id, run_id, config=config).run_stage("translate-range")

        assert result.success is True
        assert translated == [2, 3]

    def test_run_stage_requested_stop_marks_state_stopped(self):
        import uuid

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"
        token = StopToken()
        token.request_stop()

        result = OrchestrationRunner(release_id, run_id).run_stage(
            "reset",
            dry_run=True,
            stop_token=token,
        )

        assert result.success is True
        assert result.stopped is True

        conn = ensure_tracking_db(release_id)
        try:
            from resemantica.tracking.repo import load_run_state

            state = load_run_state(conn, run_id)
            events = load_events(conn, run_id=run_id, release_id=release_id)
        finally:
            conn.close()

        assert state is not None
        assert state.status == "stopped"
        assert state.metadata["interrupt_report"]["stage"] == "reset"
        assert [event.event_type for event in events].count("reset.stopped") == 1

    def test_stage_completed_event_persists_llm_usage_payload(self, monkeypatch):
        import uuid

        from resemantica.orchestration.models import StageResult

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        def fake_execute_stage(self, stage_name, **kwargs):
            return StageResult(
                True,
                stage_name,
                "ok",
                metadata={"llm_total_tokens": 33, "llm_request_count": 2},
            )

        monkeypatch.setattr(OrchestrationRunner, "_execute_stage", fake_execute_stage)

        result = OrchestrationRunner(release_id, run_id).run_stage("reset", dry_run=True)

        assert result.success is True
        conn = ensure_tracking_db(release_id)
        try:
            events = load_events(conn, run_id=run_id, release_id=release_id, limit=10)
        finally:
            conn.close()

        completed = next(event for event in events if event.event_type == "reset.completed")
        assert completed.payload["llm_total_tokens"] == 33
        assert completed.payload["llm_request_count"] == 2

    def test_translate_range_stop_after_chapter_does_not_start_next(self, monkeypatch):
        import uuid

        from resemantica.orchestration.models import StageResult
        from resemantica.settings import load_config

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"
        token = StopToken()
        translated: list[int] = []

        monkeypatch.setattr(
            OrchestrationRunner,
            "_resolve_chapter_range",
            lambda self, chapter_start, chapter_end: (1, 3),
        )

        def fake_translate_chapter(
            self,
            *,
            chapter_number: int,
            force: bool = False,
            stop_token=None,
            llm_client=None,
        ):
            translated.append(chapter_number)
            if chapter_number == 1:
                token.request_stop()
            return StageResult(True, "translate-chapter", "ok")

        monkeypatch.setattr(OrchestrationRunner, "_translate_chapter", fake_translate_chapter)

        config = load_config()
        config.translation.batched_model_order = False
        result = OrchestrationRunner(release_id, run_id, config=config).run_stage(
            "translate-range",
            chapter_start=1,
            chapter_end=3,
            stop_token=token,
        )

        assert result.stopped is True
        assert translated == [1]


class TestRetryFailed:
    @staticmethod
    def _write_extracted_chapter(release_id: str, chapter_number: int) -> None:
        import json

        from resemantica.settings import derive_paths, load_config

        paths = derive_paths(load_config(), release_id=release_id)
        paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "chapter_id": f"chapter-{chapter_number}",
            "chapter_number": chapter_number,
            "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
            "chapter_source_hash": f"hash-ch{chapter_number}",
            "schema_version": 1,
            "records": [],
        }
        (paths.extracted_chapters_dir / f"chapter-{chapter_number}.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def test_retry_failed_dry_run_reports_summary_failure(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        release_id = "retry-summary"
        run_id = "production"
        self._write_extracted_chapter(release_id, 1)
        self._write_extracted_chapter(release_id, 2)

        from resemantica.db.sqlite import open_connection
        from resemantica.db.summary_repo import ensure_summary_schema, save_summary_draft, set_summary_checkpoint
        from resemantica.settings import derive_paths, load_config

        paths = derive_paths(load_config(), release_id=release_id)
        manifest_path = paths.extracted_chapter_manifest_path
        assert not manifest_path.exists()
        conn = open_connection(paths.db_path)
        ensure_summary_schema(conn)
        try:
            save_summary_draft(
                conn,
                release_id=release_id,
                chapter_number=1,
                summary_type="chapter_summary_zh_structured",
                content={"failure_category": "parse_failed", "validation_errors": ["invalid JSON object"]},
                chapter_source_hash="hash-ch1",
                model_name="model",
                prompt_version="1",
                run_id=run_id,
                validation_status="failed",
                is_story_chapter=1,
            )
            set_summary_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                zh_last_chapter=1,
                story_last_chapter=1,
                en_last_chapter=1,
            )
        finally:
            conn.close()

        plan = plan_retry_failed(
            release_id=release_id,
            run_id=run_id,
            stage="preprocess-summaries",
        )

        assert len(plan.retryable) == 1
        unit = plan.retryable[0]
        assert unit.stage == "preprocess-summaries"
        assert unit.chapter_start == 1
        assert unit.chapter_end == 2
        assert unit.reason == "failed_or_missing_summary_rows"
        assert not manifest_path.exists()

    def test_retry_failed_uses_empty_checkpoint_and_restores_production_state(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        release_id = "retry-checkpoint-preservation"
        run_id = "001"
        original = RunState(
            run_id=run_id,
            release_id=release_id,
            stage_name="translate-range",
            status="stopped",
            checkpoint={"pass1_completed": [1, 2], "chapter_end": 1248},
            metadata={"production": True},
        )
        conn = ensure_tracking_db(release_id)
        try:
            save_run_state(conn, original)
        finally:
            conn.close()

        from resemantica.orchestration.models import StageResult
        from resemantica.orchestration.retry_failed import RetryFailedPlan, RetryUnit

        plan = RetryFailedPlan(
            release_id=release_id,
            run_id=run_id,
            stage="translate-range",
            retryable=[RetryUnit("translate-range", 3, 3, "failed", [3])],
        )
        monkeypatch.setattr("resemantica.orchestration.retry_failed.plan_retry_failed", lambda **kwargs: plan)
        seen_checkpoints: list[dict[str, object]] = []

        def fake_execute(self, stage_name, **kwargs):
            seen_checkpoints.append(dict(kwargs["checkpoint"]))
            return StageResult(True, stage_name, "repaired", checkpoint={"completed_chapters": [3]})

        monkeypatch.setattr(OrchestrationRunner, "_execute_stage", fake_execute)

        result = execute_retry_failed(
            release_id=release_id,
            run_id=run_id,
            stage="translate-range",
        )

        assert result.success is True
        assert seen_checkpoints == [{}]
        conn = ensure_tracking_db(release_id)
        try:
            restored = load_run_state(conn, run_id)
        finally:
            conn.close()
        assert restored == original

    def test_retry_failed_propagates_graceful_stop_without_failure_event(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        release_id = "retry-graceful-stop"
        run_id = "001"

        from resemantica.orchestration.models import StageResult
        from resemantica.orchestration.retry_failed import RetryFailedPlan, RetryUnit

        plan = RetryFailedPlan(
            release_id=release_id,
            run_id=run_id,
            stage="translate-range",
            retryable=[RetryUnit("translate-range", 3, 3, "failed", [3])],
        )
        monkeypatch.setattr("resemantica.orchestration.retry_failed.plan_retry_failed", lambda **kwargs: plan)
        token = StopToken()
        seen_tokens: list[StopToken | None] = []

        def fake_run_stage(self, stage_name, **kwargs):
            seen_tokens.append(kwargs.get("stop_token"))
            return StageResult(
                True,
                stage_name,
                "drained",
                checkpoint={"completed_chapters": [3]},
                metadata={
                    "interrupt_report": {
                        "stage": stage_name,
                        "phase": "pass2",
                        "drained_count": 1,
                        "canceled_count": 2,
                    }
                },
                stopped=True,
            )

        monkeypatch.setattr(OrchestrationRunner, "run_stage", fake_run_stage)

        result = execute_retry_failed(
            release_id=release_id,
            run_id=run_id,
            stage="translate-range",
            stop_token=token,
        )

        assert result.stopped is True
        assert result.metadata["interrupt_report"]["canceled_count"] == 2
        assert seen_tokens == [token]
        conn = ensure_tracking_db(release_id)
        try:
            events = load_events(conn, run_id=run_id, release_id=release_id)
        finally:
            conn.close()
        event_types = [event.event_type for event in events]
        assert "retry-failed.stopped" in event_types
        assert "retry-failed.failed" not in event_types

    def test_retry_failed_reports_llm_content_validation_summary_failure(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        release_id = "retry-summary-llm-validation"
        run_id = "production"
        self._write_extracted_chapter(release_id, 1)

        from resemantica.db.sqlite import open_connection
        from resemantica.db.summary_repo import (
            ensure_summary_schema,
            save_chapter_structured_and_short,
            save_summary_draft,
        )
        from resemantica.settings import derive_paths, load_config

        paths = derive_paths(load_config(), release_id=release_id)
        conn = open_connection(paths.db_path)
        ensure_summary_schema(conn)
        try:
            save_summary_draft(
                conn,
                release_id=release_id,
                chapter_number=1,
                summary_type="chapter_summary_zh_structured",
                content={
                    "failure_category": "llm_content_validation_failed",
                    "validation_errors": ["llm_validation_flag: unsupported_claim"],
                    "llm_validation_flags": ["unsupported_claim"],
                },
                chapter_source_hash="hash-ch1",
                model_name="model",
                prompt_version="1",
                run_id=run_id,
                validation_status="failed",
                is_story_chapter=1,
            )
            save_chapter_structured_and_short(
                conn,
                release_id=release_id,
                chapter_number=1,
                structured_summary={"is_story_chapter": True, "narrative_progression": "失败摘要。"},
                narrative_progression="失败摘要。",
                derived_from_chapter_hash="hash-ch1",
                run_id=run_id,
                validation_status="failed",
            )
        finally:
            conn.close()

        plan = plan_retry_failed(
            release_id=release_id,
            run_id=run_id,
            stage="preprocess-summaries",
        )

        assert len(plan.retryable) == 1
        assert plan.retryable[0].stage == "preprocess-summaries"
        assert plan.retryable[0].chapters == [1]
        assert plan.retryable[0].reason == "llm_content_validation_failed"

    def test_retry_failed_reports_glossary_conflict_as_non_retryable(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        release_id = "retry-glossary-conflict"
        run_id = "production"

        from resemantica.db.glossary_repo import ensure_glossary_schema, insert_conflicts
        from resemantica.db.sqlite import open_connection
        from resemantica.glossary.models import GlossaryConflict
        from resemantica.settings import derive_paths, load_config

        paths = derive_paths(load_config(), release_id=release_id)
        conn = open_connection(paths.db_path)
        ensure_glossary_schema(conn)
        try:
            with conn:
                insert_conflicts(
                    conn,
                    conflicts=[
                        GlossaryConflict(
                            conflict_id="conflict-1",
                            release_id=release_id,
                            candidate_id="candidate-1",
                            conflict_type="canon_conflict",
                            conflict_reason="duplicate",
                            existing_glossary_id="glex-1",
                        )
                    ],
                )
        finally:
            conn.close()

        plan = plan_retry_failed(
            release_id=release_id,
            run_id=run_id,
            stage="preprocess-glossary",
        )

        assert plan.retryable == []
        assert len(plan.non_retryable) == 1
        assert "conflict" in plan.non_retryable[0].reason

    def test_retry_failed_reports_missing_graph_draft(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        release_id = "retry-graph-missing"
        run_id = "production"
        self._write_extracted_chapter(release_id, 1)

        plan = plan_retry_failed(
            release_id=release_id,
            run_id=run_id,
            stage="preprocess-graph",
        )

        assert len(plan.retryable) == 1
        assert plan.retryable[0].stage == "preprocess-graph"
        assert plan.retryable[0].chapters == [1]
        assert plan.retryable[0].reason == "missing_or_stale_graph_draft_or_failed_validation"

    def test_retry_failed_reports_stale_graph_prompt_draft(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        release_id = "retry-graph-stale-prompt"
        run_id = "production"
        self._write_extracted_chapter(release_id, 1)

        from resemantica.db.graph_repo import ensure_graph_schema, save_graph_extraction_draft
        from resemantica.db.sqlite import open_connection
        from resemantica.settings import derive_paths, load_config

        paths = derive_paths(load_config(), release_id=release_id)
        conn = open_connection(paths.db_path)
        ensure_graph_schema(conn)
        try:
            save_graph_extraction_draft(
                conn,
                release_id=release_id,
                run_id=run_id,
                chapter_number=1,
                chapter_source_hash="hash-ch1",
                prompt_version="stale",
                payload={
                    "provisional_entities": [],
                    "provisional_aliases": [],
                    "provisional_appearances": [],
                    "provisional_relationships": [],
                    "deferred_entities": [],
                    "warnings": [],
                },
            )
        finally:
            conn.close()

        plan = plan_retry_failed(
            release_id=release_id,
            run_id=run_id,
            stage="preprocess-graph",
        )

        assert len(plan.retryable) == 1
        assert plan.retryable[0].chapters == [1]
        assert plan.retryable[0].reason == "missing_or_stale_graph_draft_or_failed_validation"

    def test_retry_failed_reuses_fresh_graph_draft_after_validation_failure(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        release_id = "retry-graph-validation"
        run_id = "production"
        self._write_extracted_chapter(release_id, 1)

        from resemantica.db.graph_repo import ensure_graph_schema, save_graph_extraction_draft
        from resemantica.db.sqlite import open_connection
        from resemantica.llm.prompts import load_prompt
        from resemantica.orchestration.events import emit_event as emit_tracking_event
        from resemantica.settings import derive_paths, load_config

        paths = derive_paths(load_config(), release_id=release_id)
        conn = open_connection(paths.db_path)
        ensure_graph_schema(conn)
        try:
            save_graph_extraction_draft(
                conn,
                release_id=release_id,
                run_id=run_id,
                chapter_number=1,
                chapter_source_hash="hash-ch1",
                prompt_version=load_prompt("graph_extract.txt").version,
                payload={
                    "provisional_entities": [],
                    "provisional_aliases": [],
                    "provisional_appearances": [],
                    "provisional_relationships": [],
                    "deferred_entities": [],
                    "warnings": [],
                },
            )
        finally:
            conn.close()
        emit_tracking_event(
            run_id,
            release_id,
            "preprocess-graph.validation_failed",
            "preprocess-graph",
            severity="error",
            chapter_number=1,
            message="Graph validation failed",
        )

        plan = plan_retry_failed(
            release_id=release_id,
            run_id=run_id,
            stage="preprocess-graph",
        )

        assert len(plan.retryable) == 1
        assert plan.retryable[0].chapters == [1]
        assert plan.retryable[0].reason == "missing_or_stale_graph_draft_or_failed_validation"

    def test_retry_failed_continuity_failed_chunk_uses_chunk_boundary(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        release_id = "retry-continuity-chunk"
        run_id = "production"
        for chapter_number in [1, 2, 3]:
            self._write_extracted_chapter(release_id, chapter_number)

        from resemantica.db.sqlite import open_connection
        from resemantica.db.summary_repo import ensure_summary_schema, save_validated_summary
        from resemantica.orchestration.chunk_checkpoints import save_chunk_checkpoint
        from resemantica.settings import derive_paths, load_config

        paths = derive_paths(load_config(), release_id=release_id)
        conn = open_connection(paths.db_path)
        ensure_summary_schema(conn)
        try:
            for chapter_number in [1, 2]:
                save_validated_summary(
                    conn,
                    release_id=release_id,
                    chapter_number=chapter_number,
                    summary_type="story_so_far_zh_graph_compact",
                    content_zh=f"第{chapter_number}章图谱连续性。",
                    derived_from_chapter_hash=f"continuity-source-{chapter_number}",
                    run_id=run_id,
                )
            save_chunk_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                stage_name="preprocess-continuity",
                chunk_index=0,
                chapter_start=1,
                chapter_end=3,
                status="failed",
                metadata={"reason": "graph_continuity_output_invalid: empty model output"},
            )
        finally:
            conn.close()

        plan = plan_retry_failed(
            release_id=release_id,
            run_id=run_id,
            stage="preprocess-continuity",
        )

        assert len(plan.retryable) == 1
        unit = plan.retryable[0]
        assert unit.stage == "preprocess-continuity"
        assert unit.chapter_start == 1
        assert unit.chapter_end == 3
        assert unit.chapters == [1, 2, 3]
        assert unit.reason == "missing_or_stale_graph_continuity_rows_artifacts_or_failed_event"

    def test_retry_failed_translation_treats_success_checkpoint_as_complete(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        release_id = "retry-translation-success"
        run_id = "production"
        self._write_extracted_chapter(release_id, 1)

        from resemantica.db.sqlite import open_connection
        from resemantica.settings import derive_paths, load_config
        from resemantica.translation.checkpoints import ensure_checkpoint_schema, save_checkpoint

        paths = derive_paths(load_config(), release_id=release_id)
        conn = open_connection(paths.db_path)
        try:
            ensure_checkpoint_schema(conn)
            save_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                chapter_number=1,
                pass_name="pass2",
                source_hash="hash-ch1",
                prompt_version="prompt",
                status="success",
                artifact_path="pass2.json",
            )
        finally:
            conn.close()

        plan = plan_retry_failed(
            release_id=release_id,
            run_id=run_id,
            stage="translate-range",
        )

        assert plan.retryable == []
        assert plan.non_retryable == []


class TestM11CleanupScopes:
    def _create_test_artifacts(self, release_id: str, run_id: str):
        from resemantica.settings import derive_paths, load_config
        cfg = load_config()
        release_root = derive_paths(cfg, release_id=release_id).release_root
        run_dir = release_root / "runs" / run_id

        # Create run artifacts
        (run_dir / "translation").mkdir(parents=True, exist_ok=True)
        (run_dir / "translation" / "chapter-1.json").write_text('{"test": 1}')
        (run_dir / "validation").mkdir(parents=True, exist_ok=True)
        (run_dir / "validation" / "chapter-1.json").write_text('{"test": 2}')

        # Create preprocess artifacts
        (release_root / "extracted" / "chapters").mkdir(parents=True, exist_ok=True)
        (release_root / "extracted" / "chapters" / "chapter-1.json").write_text('{"test": 3}')
        (release_root / "glossary").mkdir(parents=True, exist_ok=True)
        (release_root / "glossary" / "candidates.json").write_text('{"test": 4}')
        (release_root / "summaries").mkdir(parents=True, exist_ok=True)
        (release_root / "summaries" / "chapter-1-zh.json").write_text('{"test": 5}')
        (release_root / "packets").mkdir(parents=True, exist_ok=True)
        (release_root / "packets" / "chapter-1-1.json").write_text('{"test": 6}')
        (release_root / ".cache").mkdir(parents=True, exist_ok=True)
        (release_root / ".cache" / "llm.json").write_text('{"test": 7}')

        # Create protected assets
        (release_root / "tracking.db").touch()
        (release_root / "resemantica.db").touch()
        (release_root / "graph.ladybug").touch()

        return release_root, run_dir

    def _seed_cleanup_db_rows(self, release_id: str, run_id: str) -> Path:
        from resemantica.db.sqlite import ensure_full_schema, open_connection
        from resemantica.db.summary_repo import save_summary_draft
        from resemantica.orchestration.chunk_checkpoints import save_chunk_checkpoint
        from resemantica.settings import derive_paths, load_config

        paths = derive_paths(load_config(), release_id=release_id)
        conn = open_connection(paths.db_path)
        try:
            ensure_full_schema(conn)
            conn.execute(
                """
                INSERT INTO translation_checkpoints(
                    release_id, run_id, chapter_number, pass_name, source_hash,
                    prompt_version, packet_version_hash, status, artifact_path
                ) VALUES (?, ?, 1, 'pass1', 'src', 'p', 'pkt', 'completed', 'artifact')
                """,
                (release_id, run_id),
            )
            conn.execute(
                """
                INSERT INTO extracted_chapters(
                    chapter_id, release_id, run_id, chapter_number,
                    source_document_path, chapter_source_hash, placeholder_map_ref,
                    created_by_stage, validation_status, schema_version, created_at, updated_at
                ) VALUES ('chapter-1', ?, ?, 1, 'chapter.xhtml', 'hash', 'none',
                          'extract', 'valid', '1', 'now', 'now')
                """,
                (release_id, run_id),
            )
            conn.execute(
                """
                INSERT INTO extracted_blocks(
                    block_id, chapter_id, release_id, run_id, chapter_number, segment_id,
                    parent_block_id, block_order, segment_order, source_text_zh,
                    placeholder_map_ref, chapter_source_hash, schema_version, created_at, updated_at
                ) VALUES ('block-1', 'chapter-1', ?, ?, 1, NULL, 'block-1', 1, NULL,
                          '文本', 'none', 'hash', '1', 'now', 'now')
                """,
                (release_id, run_id),
            )
            conn.execute(
                """
                INSERT INTO summary_checkpoints(
                    release_id, run_id, zh_last_chapter, story_last_chapter, en_last_chapter
                ) VALUES (?, ?, 1, 1, 1)
                """,
                (release_id, run_id),
            )
            conn.execute(
                """
                INSERT INTO glossary_discovery_chapter_state(
                    release_id, run_id, chapter_number, chapter_source_hash, input_hash,
                    status, skip_reason, raw_candidates_json, candidate_count
                ) VALUES (?, ?, 1, 'src', 'input', 'completed', NULL, '[]', 0)
                """,
                (release_id, run_id),
            )
            save_chunk_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                stage_name="preprocess-summaries",
                chunk_index=0,
                chapter_start=1,
                chapter_end=1,
                status="completed",
                metadata={"last_good_chapter": 1},
            )
            save_summary_draft(
                conn,
                release_id=release_id,
                chapter_number=1,
                summary_type="chapter_summary_zh_structured",
                content={"chapter_number": 1, "is_story_chapter": True},
                chapter_source_hash="hash",
                model_name="model",
                prompt_version="prompt",
                run_id=run_id,
                validation_status="approved",
                is_story_chapter=1,
            )
            conn.execute(
                """
                INSERT INTO packet_metadata(
                    packet_id, release_id, chapter_number, run_id, packet_path, bundle_path,
                    packet_hash, chapter_source_hash, glossary_version_hash, summary_version_hash,
                    graph_snapshot_hash, idiom_policy_hash, packet_builder_version
                ) VALUES ('packet-1', ?, 1, ?, 'packet.json', 'bundle.json',
                          'packet-hash', 'chapter-hash', 'glossary-hash', 'summary-hash',
                          'graph-hash', 'idiom-hash', 'v1')
                """,
                (release_id, run_id),
            )
            conn.commit()
        finally:
            conn.close()
        return paths.db_path

    @staticmethod
    def _write_extracted_summary_chapter(
        release_id: str,
        chapter_number: int,
        *,
        source_text: str | None = None,
    ) -> None:
        import json

        from resemantica.settings import derive_paths, load_config

        paths = derive_paths(load_config(), release_id=release_id)
        paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
        block_id = f"ch{chapter_number:03d}_blk001"
        source_path = f"OEBPS/chapter{chapter_number}.xhtml"
        payload = {
            "chapter_id": f"chapter-{chapter_number}",
            "chapter_number": chapter_number,
            "source_document_path": source_path,
            "chapter_source_hash": f"hash-ch{chapter_number}",
            "schema_version": 1,
            "records": [
                {
                    "chapter_id": f"chapter-{chapter_number}",
                    "chapter_number": chapter_number,
                    "source_document_path": source_path,
                    "block_id": block_id,
                    "parent_block_id": block_id,
                    "segment_id": None,
                    "block_order": 1,
                    "segment_order": None,
                    "source_text_zh": source_text or f"第{chapter_number}章内容。",
                    "placeholder_map_ref": str(
                        (paths.extracted_placeholders_dir / f"chapter-{chapter_number}.json").as_posix()
                    ),
                    "chapter_source_hash": f"hash-ch{chapter_number}",
                    "schema_version": 1,
                }
            ],
        }
        (paths.extracted_chapters_dir / f"chapter-{chapter_number}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def _count_rows(db_path: Path, table: str) -> int:
        from resemantica.db.sqlite import open_connection

        conn = open_connection(db_path)
        try:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            return int(row["count"])
        finally:
            conn.close()

    def test_scope_run_deletes_only_run_dir(self, tmp_path: Path):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        release_root, run_dir = self._create_test_artifacts(release_id, run_id)

        plan = plan_cleanup(release_id, run_id, scope="run", dry_run=True)
        assert len(plan["deletable_artifacts"]) == 1
        assert str(run_dir) in plan["deletable_artifacts"]

        # Apply cleanup
        apply_cleanup(release_id, run_id, scope="run")
        assert run_dir.exists() is False
        # Preprocess artifacts should still exist
        assert (release_root / "extracted").exists()

    def test_scope_translation_deletes_only_translation(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        release_root, run_dir = self._create_test_artifacts(release_id, run_id)

        plan = plan_cleanup(release_id, run_id, scope="translation", dry_run=True)
        assert any("translation" in a for a in plan["deletable_artifacts"])
        assert not any("validation" in a for a in plan["deletable_artifacts"])

    def test_scope_preprocess_deletes_preprocess_artifacts(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        release_root, run_dir = self._create_test_artifacts(release_id, run_id)

        plan = plan_cleanup(release_id, run_id, scope="preprocess", dry_run=True)
        assert any("extracted" in a for a in plan["deletable_artifacts"])
        assert any("glossary" in a for a in plan["deletable_artifacts"])
        assert any("summaries" in a for a in plan["deletable_artifacts"])
        # Run dir should NOT be in deletable
        assert not any("runs" in a for a in plan["deletable_artifacts"])

    def test_scope_keep_extracted_preserves_extraction_and_deletes_downstream(self):
        import uuid

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        release_root, run_dir = self._create_test_artifacts(release_id, run_id)
        db_path = self._seed_cleanup_db_rows(release_id, run_id)

        plan = plan_cleanup(release_id, run_id, scope="keep-extracted", dry_run=True)
        assert str(release_root / "extracted") in plan["preserved_artifacts"]
        assert str(release_root / "extracted") not in plan["deletable_artifacts"]
        assert str(release_root / "summaries") in plan["deletable_artifacts"]
        assert str(run_dir / "translation") in plan["deletable_artifacts"]
        assert not any(row["table"] == "extracted_chapters" for row in plan["sqlite_rows"])
        assert not any(row["table"] == "extracted_blocks" for row in plan["sqlite_rows"])
        assert any(row["table"] == "summary_checkpoints" for row in plan["sqlite_rows"])
        assert any(
            row["table"] == "chunk_checkpoints" and row.get("stage_name") == "preprocess-summaries"
            for row in plan["sqlite_rows"]
        )

        result = apply_cleanup(release_id, run_id, scope="keep-extracted")

        assert result["success"] is True
        assert (release_root / "extracted").exists()
        assert not (release_root / "summaries").exists()
        assert not (run_dir / "translation").exists()
        assert self._count_rows(db_path, "extracted_chapters") == 1
        assert self._count_rows(db_path, "extracted_blocks") == 1
        assert self._count_rows(db_path, "summary_checkpoints") == 0
        assert self._count_rows(db_path, "chunk_checkpoints") == 0
        assert self._count_rows(db_path, "summary_drafts") == 0
        assert self._count_rows(db_path, "glossary_discovery_chapter_state") == 0
        assert self._count_rows(db_path, "packet_metadata") == 0
        assert self._count_rows(db_path, "translation_checkpoints") == 0

    def test_broad_cleanup_scopes_include_summary_resume_targets(self):
        import uuid

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        for scope in ["run", "preprocess", "keep-extracted", "all"]:
            plan = plan_cleanup(release_id, run_id, scope=scope, dry_run=True)
            identities = {
                (
                    row.get("database"),
                    row.get("table"),
                    row.get("column"),
                    row.get("release_column"),
                    row.get("stage_name"),
                )
                for row in plan["sqlite_rows"]
            }
            assert ("resemantica.db", "summary_checkpoints", "run_id", "release_id", None) in identities
            assert (
                "resemantica.db",
                "glossary_discovery_chapter_state",
                "run_id",
                "release_id",
                None,
            ) in identities
            assert (
                "resemantica.db",
                "chunk_checkpoints",
                "run_id",
                "release_id",
                "preprocess-summaries",
            ) in identities

    def test_cleanup_apply_rejects_stale_keep_extracted_plan(self):
        import json
        import uuid

        from resemantica.orchestration.cleanup import _get_cleanup_plan_path

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        release_root, run_dir = self._create_test_artifacts(release_id, run_id)
        db_path = self._seed_cleanup_db_rows(release_id, run_id)
        plan = plan_cleanup(release_id, run_id, scope="keep-extracted", dry_run=True)
        plan["sqlite_rows"] = [
            row
            for row in plan["sqlite_rows"]
            if not (row["table"] == "chunk_checkpoints" and row.get("stage_name") == "preprocess-summaries")
        ]
        plan_path = _get_cleanup_plan_path(release_id, scope="keep-extracted")
        plan_path.write_text(json.dumps(plan), encoding="utf-8")

        result = apply_cleanup(release_id, run_id, scope="keep-extracted")

        assert result["success"] is False
        assert "stale or incomplete" in result["message"]
        assert (release_root / "summaries").exists()
        assert (run_dir / "translation").exists()
        assert self._count_rows(db_path, "summary_checkpoints") == 1
        assert self._count_rows(db_path, "chunk_checkpoints") == 1
        assert self._count_rows(db_path, "summary_drafts") == 1

    def test_keep_extracted_cleanup_allows_summary_rerun_from_first_chapter(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        import json

        from resemantica.db.sqlite import ensure_full_schema, open_connection
        from resemantica.db.summary_repo import get_summary_checkpoint, save_summary_draft
        from resemantica.orchestration.chunk_checkpoints import save_chunk_checkpoint
        from resemantica.settings import derive_paths, load_config
        from resemantica.summaries.pipeline import preprocess_summaries

        monkeypatch.chdir(tmp_path)
        release_id = "cleanup-summary-rerun"
        run_id = "summaries-001"
        config = load_config()
        config.batch_order.enabled = True
        config.batch_order.summary_chunk_multiplier = 2
        config.summaries.chapter_concurrency = 1
        for chapter_number in range(1, 5):
            self._write_extracted_summary_chapter(release_id, chapter_number)

        paths = derive_paths(config, release_id=release_id)
        conn = open_connection(paths.db_path)
        try:
            ensure_full_schema(conn)
            conn.execute(
                """
                INSERT INTO summary_checkpoints(
                    release_id, run_id, zh_last_chapter, story_last_chapter, en_last_chapter
                ) VALUES (?, ?, 4, 4, 4)
                """,
                (release_id, run_id),
            )
            save_chunk_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                stage_name="preprocess-summaries",
                chunk_index=0,
                chapter_start=1,
                chapter_end=2,
                status="completed",
                metadata={"last_good_chapter": 2},
            )
            save_summary_draft(
                conn,
                release_id=release_id,
                chapter_number=1,
                summary_type="chapter_summary_zh_structured",
                content={"chapter_number": 1, "is_story_chapter": True},
                chapter_source_hash="hash-ch1",
                model_name="model",
                prompt_version="prompt",
                run_id=run_id,
                validation_status="approved",
                is_story_chapter=1,
            )
            conn.commit()
        finally:
            conn.close()

        plan_cleanup(release_id, run_id, scope="keep-extracted", dry_run=True)
        result = apply_cleanup(release_id, run_id, scope="keep-extracted")
        assert result["success"] is True

        conn = open_connection(paths.db_path)
        try:
            assert get_summary_checkpoint(conn, release_id=release_id, run_id=run_id) is None
            assert self._count_rows(paths.db_path, "summary_drafts") == 0
            assert self._count_rows(paths.db_path, "chunk_checkpoints") == 0
        finally:
            conn.close()

        structured_calls: list[int] = []

        class RecordingLLM:
            def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
                if "SUMMARY_ZH_STRUCTURED" in prompt:
                    import re

                    chapter_match = re.search(r"## CHAPTER NUMBER\s+(\d+)", prompt)
                    if chapter_match is None:
                        raise RuntimeError("chapter number missing from prompt")
                    chapter_number = int(chapter_match.group(1))
                    structured_calls.append(chapter_number)
                    return json.dumps({
                        "chapter_number": chapter_number,
                        "characters_mentioned": ["张三"],
                        "key_events": ["张三开始修炼"],
                        "new_terms": [],
                        "relationships_changed": [{"entity": "张三", "change": "开始修炼"}],
                        "setting": "山中",
                        "tone": "calm",
                        "narrative_progression": "张三开始修炼。",
                        "is_story_chapter": True,
                    }, ensure_ascii=False)
                if "SUMMARY_EN_DERIVE" in prompt:
                    return "EN::content"
                if "SUMMARY_STORY_COMPACT" in prompt:
                    return "张三开始修炼。"
                if "SUMMARY_ZH_VALIDATE" in prompt:
                    return json.dumps({"flags": [], "warnings": []}, ensure_ascii=False)
                raise RuntimeError("Unexpected prompt")

        summary_result = preprocess_summaries(
            release_id=release_id,
            run_id=run_id,
            config=config,
            llm_client=RecordingLLM(),
            resume=True,
        )

        assert summary_result["status"] == "success"
        assert structured_calls == [1, 2, 3, 4]

    def test_scope_cache_deletes_no_sqlite_rows(self):
        import uuid

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        release_root, _run_dir = self._create_test_artifacts(release_id, run_id)
        db_path = self._seed_cleanup_db_rows(release_id, run_id)

        plan = plan_cleanup(release_id, run_id, scope="cache", dry_run=True)
        assert str(release_root / ".cache") in plan["deletable_artifacts"]
        assert plan["sqlite_rows"] == []

        result = apply_cleanup(release_id, run_id, scope="cache")

        assert result["success"] is True
        assert not (release_root / ".cache").exists()
        assert self._count_rows(db_path, "translation_checkpoints") == 1
        assert self._count_rows(db_path, "extracted_chapters") == 1

    def test_scope_all_preserves_release_stores(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        release_root, run_dir = self._create_test_artifacts(release_id, run_id)

        plan = plan_cleanup(release_id, run_id, scope="all", dry_run=True)
        assert str(release_root / "tracking.db") in plan["preserved_artifacts"]
        assert str(release_root / "resemantica.db") in plan["preserved_artifacts"]
        assert str(release_root / "graph.ladybug") in plan["preserved_artifacts"]

    def test_cleanup_apply_refuses_without_plan(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        result = apply_cleanup(release_id, run_id, scope="run")
        assert result["success"] is False
        assert "No cleanup plan found" in result["message"]

    def test_cleanup_apply_refuses_scope_mismatch(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        plan_cleanup(release_id, run_id, scope="run", dry_run=True)
        result = apply_cleanup(release_id, run_id, scope="all")
        assert result["success"] is False
        assert "scope" in result["message"].lower()

    def test_cleanup_apply_refuses_release_mismatch_even_with_force(self):
        import json
        import uuid

        from resemantica.orchestration.cleanup import _get_cleanup_plan_path

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        self._create_test_artifacts(release_id, run_id)
        plan = plan_cleanup(release_id, run_id, scope="run", dry_run=True)
        plan["release_id"] = f"test-release-{uuid.uuid4().hex[:8]}"
        plan_path = _get_cleanup_plan_path(release_id, scope="run")
        plan_path.write_text(json.dumps(plan), encoding="utf-8")

        result = apply_cleanup(release_id, run_id, scope="run", force=True)

        assert result["success"] is False
        assert "release" in result["message"].lower()

    def test_cleanup_apply_refuses_out_of_root_plan_target(self):
        import json
        import uuid

        from resemantica.orchestration.cleanup import _get_cleanup_plan_path

        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        self._create_test_artifacts(release_id, run_id)
        plan = plan_cleanup(release_id, run_id, scope="run", dry_run=True)
        plan["deletable_artifacts"] = [str(Path.cwd().parent)]
        plan_path = _get_cleanup_plan_path(release_id, scope="run")
        plan_path.write_text(json.dumps(plan), encoding="utf-8")

        result = apply_cleanup(release_id, run_id, scope="run")

        assert result["success"] is False
        assert "outside expected root" in result["message"]

    def test_cleanup_report_generated(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        self._create_test_artifacts(release_id, run_id)
        plan_cleanup(release_id, run_id, scope="run", dry_run=True)
        apply_cleanup(release_id, run_id, scope="run")

        from resemantica.orchestration.cleanup import _get_cleanup_report_path
        report_path = _get_cleanup_report_path(release_id)
        assert report_path.exists()

        import json
        with open(report_path) as f:
            report = json.load(f)
        assert "deleted_dirs" in report
        assert "sqlite_rows_deleted" in report

    def test_factory_scope_plan_creates_factory_plan(self):
        import uuid

        from resemantica.settings import load_config

        release_id = f"test-factory-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        plan = plan_cleanup(release_id, run_id, scope="factory", dry_run=True)

        assert plan["scope"] == "factory"
        assert plan["sqlite_rows"] == []
        assert plan["release_id"] == release_id
        assert plan["run_id"] == run_id

        cfg = load_config()
        plan_path = Path(cfg.paths.artifact_root) / "factory_cleanup_plan.json"
        assert plan_path.exists()

    def test_factory_scope_apply_requires_plan(self):
        import uuid

        from resemantica.settings import load_config as _load_config

        release_id = f"test-factory-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        # Clean up any stale factory plan from other tests
        cfg = _load_config()
        plan_path = Path(cfg.paths.artifact_root) / "factory_cleanup_plan.json"
        if plan_path.exists():
            plan_path.unlink()

        result = apply_cleanup(release_id, run_id, scope="factory")
        assert result["success"] is False
        assert "No cleanup plan found" in result["message"]

    def test_factory_scope_apply_deletes_artifacts(self, monkeypatch, tmp_path):
        import uuid

        release_id = f"test-factory-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        class MockPaths:
            artifact_root = str(tmp_path)
            db_filename = "resemantica.db"

        class MockConfig:
            paths = MockPaths()

        monkeypatch.setattr("resemantica.orchestration.cleanup.load_config", lambda: MockConfig())

        releases_dir = tmp_path / "releases"
        (releases_dir / release_id / "runs" / run_id).mkdir(parents=True, exist_ok=True)
        (releases_dir / release_id / "runs" / run_id / "test.txt").write_text("test")
        global_db = tmp_path / "resemantica.db"
        global_db.write_text("test")
        global_graph_db = tmp_path / "graph.ladybug"
        global_graph_db.write_text("test")

        plan_cleanup(release_id, run_id, scope="factory", dry_run=True)
        apply_cleanup(release_id, run_id, scope="factory")

        assert not releases_dir.exists()
        assert not global_db.exists()
        assert not global_graph_db.exists()

    def test_last_good_chunk_summary_cleanup_rewinds_boundary(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        release_id = "cleanup-summary-chunk"
        run_id = "production"
        from resemantica.db.sqlite import ensure_full_schema, open_connection
        from resemantica.orchestration.chunk_checkpoints import save_chunk_checkpoint
        from resemantica.settings import derive_paths, load_config

        paths = derive_paths(load_config(), release_id=release_id)
        paths.summaries_dir.mkdir(parents=True, exist_ok=True)
        (paths.summaries_dir / "chapter-10-zh.json").write_text("{}")
        (paths.summaries_dir / "chapter-11-zh.json").write_text("{}")
        conn = open_connection(paths.db_path)
        try:
            ensure_full_schema(conn)
            save_chunk_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                stage_name="preprocess-summaries",
                chunk_index=0,
                chapter_start=1,
                chapter_end=10,
                status="completed",
            )
            conn.execute(
                """
                INSERT INTO summary_checkpoints(
                    release_id, run_id, zh_last_chapter, story_last_chapter, en_last_chapter
                ) VALUES (?, ?, 12, 12, 11)
                """,
                (release_id, run_id),
            )
            conn.execute(
                """
                INSERT INTO derived_summaries_en(
                    summary_id, release_id, chapter_number, summary_type, content_en,
                    source_summary_id, source_summary_hash, glossary_version_hash,
                    model_name, prompt_version, run_id
                ) VALUES ('sum-11', ?, 11, 'story_so_far_en', 'en', 'src', 'hash',
                          'gloss', 'model', 'prompt', ?)
                """,
                (release_id, run_id),
            )
            conn.commit()
        finally:
            conn.close()

        plan = plan_cleanup(
            release_id,
            run_id,
            scope="last-good-chunk",
            stage="preprocess-summaries",
        )
        assert plan["last_good_chapter"] == 10
        assert str(paths.summaries_dir / "chapter-11-zh.json") in plan["deletable_artifacts"]
        assert str(paths.summaries_dir / "chapter-10-zh.json") in plan["preserved_artifacts"]

        result = apply_cleanup(
            release_id,
            run_id,
            scope="last-good-chunk",
            stage="preprocess-summaries",
        )
        assert result["success"] is True
        assert not (paths.summaries_dir / "chapter-11-zh.json").exists()
        assert (paths.summaries_dir / "chapter-10-zh.json").exists()

        conn = open_connection(paths.db_path)
        try:
            cp = conn.execute(
                "SELECT zh_last_chapter, story_last_chapter, en_last_chapter "
                "FROM summary_checkpoints WHERE release_id = ? AND run_id = ?",
                (release_id, run_id),
            ).fetchone()
            rows_after_boundary = conn.execute(
                "SELECT COUNT(*) AS count FROM derived_summaries_en "
                "WHERE release_id = ? AND run_id = ? AND chapter_number > 10",
                (release_id, run_id),
            ).fetchone()
        finally:
            conn.close()
        assert tuple(cp) == (10, 10, 10)
        assert int(rows_after_boundary["count"]) == 0

    def test_last_good_chunk_translation_cleanup_removes_later_artifacts(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        release_id = "cleanup-translation-chunk"
        run_id = "production"
        from resemantica.db.sqlite import ensure_full_schema, open_connection
        from resemantica.orchestration.chunk_checkpoints import save_chunk_checkpoint
        from resemantica.settings import derive_paths, load_config

        paths = derive_paths(load_config(), release_id=release_id)
        translation_root = paths.release_root / "runs" / run_id / "translation"
        (translation_root / "chapter-10").mkdir(parents=True, exist_ok=True)
        (translation_root / "chapter-10" / "pass3.json").write_text("{}")
        (translation_root / "chapter-11").mkdir(parents=True, exist_ok=True)
        (translation_root / "chapter-11" / "pass1.json").write_text("{}")
        conn = open_connection(paths.db_path)
        try:
            ensure_full_schema(conn)
            save_chunk_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                stage_name="translate-range",
                chunk_index=0,
                chapter_start=1,
                chapter_end=10,
                status="completed",
            )
            conn.execute(
                """
                INSERT INTO translation_checkpoints(
                    release_id, run_id, chapter_number, pass_name, source_hash,
                    prompt_version, status, artifact_path
                ) VALUES (?, ?, 11, 'pass1', 'src', 'prompt', 'success', 'artifact')
                """,
                (release_id, run_id),
            )
            conn.commit()
        finally:
            conn.close()

        plan = plan_cleanup(
            release_id,
            run_id,
            scope="last-good-chunk",
            stage="translate-range",
        )
        assert str(translation_root / "chapter-11") in plan["deletable_artifacts"]
        assert str(translation_root / "chapter-10") in plan["preserved_artifacts"]

        result = apply_cleanup(
            release_id,
            run_id,
            scope="last-good-chunk",
            stage="translate-range",
        )
        assert result["success"] is True
        assert not (translation_root / "chapter-11").exists()
        assert (translation_root / "chapter-10").exists()

        conn = open_connection(paths.db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM translation_checkpoints "
                "WHERE release_id = ? AND run_id = ?",
                (release_id, run_id),
            ).fetchone()
        finally:
            conn.close()
        assert int(row["count"]) == 0
