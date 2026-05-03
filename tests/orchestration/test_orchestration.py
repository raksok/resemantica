from __future__ import annotations

from pathlib import Path
from typing import Any

from resemantica.orchestration import (
    OrchestrationRunner,
    apply_cleanup,
    emit_event,
    plan_cleanup,
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

    def test_runner_production_dry_run_returns_ordered_graph(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        result = OrchestrationRunner(release_id, run_id).run_production(dry_run=True)

        assert result.success is True
        assert [stage["stage_name"] for stage in result.metadata["stages"]] == STAGE_ORDER

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
        paths = derive_paths(load_config(), release_id=release_id)
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

        result = OrchestrationRunner(release_id, run_id).run_stage("translate-range")

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

        result = OrchestrationRunner(release_id, run_id).run_stage(
            "translate-range",
            chapter_start=1,
            chapter_end=3,
            stop_token=token,
        )

        assert result.stopped is True
        assert translated == [1]


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

        # Create protected assets
        (release_root / "tracking.db").touch()

        return release_root, run_dir

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

    def test_scope_all_preserves_tracking_db(self):
        import uuid
        release_id = f"test-release-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        release_root, run_dir = self._create_test_artifacts(release_id, run_id)

        plan = plan_cleanup(release_id, run_id, scope="all", dry_run=True)
        assert str(release_root / "tracking.db") in plan["preserved_artifacts"]

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

        plan_cleanup(release_id, run_id, scope="factory", dry_run=True)
        apply_cleanup(release_id, run_id, scope="factory")

        assert not releases_dir.exists()
        assert not global_db.exists()
