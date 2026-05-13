from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from resemantica.orchestration.runner import OrchestrationRunner
from resemantica.settings import AppConfig, TranslationConfig, derive_paths, load_config
from resemantica.tracking.models import RunState
from resemantica.tracking.repo import ensure_tracking_db, save_run_state


def _write_chapter(release_id: str, number: int) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
    (paths.extracted_chapters_dir / f"chapter-{number}.json").write_text(
        json.dumps({"chapter_number": number, "chapter_source_hash": f"hash-{number}"}),
        encoding="utf-8",
    )


def test_batched_translate_range_runs_all_pass1_then_pass2_then_pass3(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "batched"
    _write_chapter(release_id, 1)
    _write_chapter(release_id, 2)
    calls: list[tuple[str, int]] = []

    def pass1(**kwargs):
        chapter = int(kwargs["chapter_number"])
        calls.append(("pass1", chapter))
        return {"status": "success", "pass1_artifact": f"p1-{chapter}.json"}

    def pass2(**kwargs):
        chapter = int(kwargs["chapter_number"])
        calls.append(("pass2", chapter))
        return {"status": "success", "pass2_artifact": f"p2-{chapter}.json"}

    def pass3(**kwargs):
        chapter = int(kwargs["chapter_number"])
        calls.append(("pass3", chapter))
        return {"status": "success", "pass3_artifact": f"p3-{chapter}.json"}

    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass1", pass1)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass2", pass2)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass3", pass3)

    result = OrchestrationRunner(release_id, "run").run_stage(
        "translate-range",
        chapter_start=1,
        chapter_end=2,
        batched_model_order=True,
    )

    assert result.success is True
    assert calls == [
        ("pass1", 1),
        ("pass1", 2),
        ("pass2", 1),
        ("pass2", 2),
        ("pass3", 1),
        ("pass3", 2),
    ]


def _seed_run_state(
    release_id: str,
    run_id: str,
    checkpoint: dict[str, Any],
) -> None:
    conn = ensure_tracking_db(release_id)
    try:
        state = RunState(
            run_id=run_id,
            release_id=release_id,
            stage_name="translate-range",
            status="stopped",
            checkpoint=checkpoint,
        )
        save_run_state(conn, state)
    finally:
        conn.close()


def _make_mock_passes(calls: list[tuple[str, int]]) -> tuple[Any, Any, Any]:
    def pass1(**kwargs):
        chapter = int(kwargs["chapter_number"])
        calls.append(("pass1", chapter))
        return {"status": "success", "pass1_artifact": f"p1-{chapter}.json"}

    def pass2(**kwargs):
        chapter = int(kwargs["chapter_number"])
        calls.append(("pass2", chapter))
        return {"status": "success", "pass2_artifact": f"p2-{chapter}.json"}

    def pass3(**kwargs):
        chapter = int(kwargs["chapter_number"])
        calls.append(("pass3", chapter))
        return {"status": "success", "pass3_artifact": f"p3-{chapter}.json"}

    return pass1, pass2, pass3


def test_resume_skips_pass1_completed_chapters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "resume-p1"
    run_id = "r01"
    for n in range(1, 6):
        _write_chapter(release_id, n)
    calls: list[tuple[str, int]] = []
    pass1, pass2, pass3 = _make_mock_passes(calls)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass1", pass1)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass2", pass2)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass3", pass3)
    _seed_run_state(
        release_id,
        run_id,
        {"pass1_completed": [1, 2], "pass2_completed": [], "pass3_completed": [], "failures": {}},
    )

    result = OrchestrationRunner(release_id, run_id).run_stage(
        "translate-range",
        chapter_start=1,
        chapter_end=5,
        batched_model_order=True,
    )

    assert result.success is True
    assert calls == [
        ("pass1", 3), ("pass1", 4), ("pass1", 5),
        ("pass2", 1), ("pass2", 2), ("pass2", 3), ("pass2", 4), ("pass2", 5),
        ("pass3", 1), ("pass3", 2), ("pass3", 3), ("pass3", 4), ("pass3", 5),
    ]
    assert result.checkpoint["pass1_completed"] == [1, 2, 3, 4, 5]
    assert result.checkpoint["pass2_completed"] == [1, 2, 3, 4, 5]
    assert result.checkpoint["pass3_completed"] == [1, 2, 3, 4, 5]


def test_resume_skips_multiple_passes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "resume-multi"
    run_id = "r01"
    for n in range(1, 6):
        _write_chapter(release_id, n)
    calls: list[tuple[str, int]] = []
    pass1, pass2, pass3 = _make_mock_passes(calls)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass1", pass1)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass2", pass2)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass3", pass3)
    _seed_run_state(
        release_id,
        run_id,
        {"pass1_completed": [1, 2, 3], "pass2_completed": [1], "pass3_completed": [], "failures": {}},
    )

    result = OrchestrationRunner(release_id, run_id).run_stage(
        "translate-range",
        chapter_start=1,
        chapter_end=5,
        batched_model_order=True,
    )

    assert result.success is True
    assert calls == [
        ("pass1", 4), ("pass1", 5),
        ("pass2", 2), ("pass2", 3), ("pass2", 4), ("pass2", 5),
        ("pass3", 1), ("pass3", 2), ("pass3", 3), ("pass3", 4), ("pass3", 5),
    ]


def test_resume_complete_is_noop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "resume-noop"
    run_id = "r01"
    for n in range(1, 4):
        _write_chapter(release_id, n)
    calls: list[tuple[str, int]] = []
    pass1, pass2, pass3 = _make_mock_passes(calls)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass1", pass1)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass2", pass2)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass3", pass3)
    _seed_run_state(
        release_id,
        run_id,
        {"pass1_completed": [1, 2, 3], "pass2_completed": [1, 2, 3], "pass3_completed": [1, 2, 3], "failures": {}},
    )

    result = OrchestrationRunner(release_id, run_id).run_stage(
        "translate-range",
        chapter_start=1,
        chapter_end=3,
        batched_model_order=True,
    )

    assert result.success is True
    assert calls == []


def test_resume_force_bypasses_checkpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "resume-force"
    run_id = "r01"
    for n in range(1, 4):
        _write_chapter(release_id, n)
    calls: list[tuple[str, int]] = []
    pass1, pass2, pass3 = _make_mock_passes(calls)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass1", pass1)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass2", pass2)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass3", pass3)
    _seed_run_state(
        release_id,
        run_id,
        {"pass1_completed": [1, 2, 3], "pass2_completed": [1, 2, 3], "pass3_completed": [1, 2, 3], "failures": {}},
    )

    result = OrchestrationRunner(release_id, run_id).run_stage(
        "translate-range",
        chapter_start=1,
        chapter_end=3,
        batched_model_order=True,
        force=True,
    )

    assert result.success is True
    assert calls == [
        ("pass1", 1), ("pass1", 2), ("pass1", 3),
        ("pass2", 1), ("pass2", 2), ("pass2", 3),
        ("pass3", 1), ("pass3", 2), ("pass3", 3),
    ]


def test_resume_no_checkpoint_processes_all(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "resume-none"
    run_id = "r01"
    for n in range(1, 4):
        _write_chapter(release_id, n)
    calls: list[tuple[str, int]] = []
    pass1, pass2, pass3 = _make_mock_passes(calls)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass1", pass1)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass2", pass2)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass3", pass3)

    result = OrchestrationRunner(release_id, run_id).run_stage(
        "translate-range",
        chapter_start=1,
        chapter_end=3,
        batched_model_order=True,
    )

    assert result.success is True
    assert calls == [
        ("pass1", 1), ("pass1", 2), ("pass1", 3),
        ("pass2", 1), ("pass2", 2), ("pass2", 3),
        ("pass3", 1), ("pass3", 2), ("pass3", 3),
    ]


def test_resume_with_failures_retries_failed_chapter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "resume-fail"
    run_id = "r01"
    for n in range(1, 6):
        _write_chapter(release_id, n)
    calls: list[tuple[str, int]] = []
    pass1, pass2, pass3 = _make_mock_passes(calls)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass1", pass1)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass2", pass2)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass3", pass3)
    _seed_run_state(
        release_id,
        run_id,
        {
            "pass1_completed": [1, 2, 4, 5],
            "pass2_completed": [],
            "pass3_completed": [],
            "failures": {3: "pass1 error"},
        },
    )

    result = OrchestrationRunner(release_id, run_id).run_stage(
        "translate-range",
        chapter_start=1,
        chapter_end=5,
        batched_model_order=True,
    )

    assert result.success is True
    assert calls == [
        ("pass1", 3),
        ("pass2", 1), ("pass2", 2), ("pass2", 4), ("pass2", 5), ("pass2", 3),
        ("pass3", 1), ("pass3", 2), ("pass3", 4), ("pass3", 5), ("pass3", 3),
    ]
    assert len(result.checkpoint["failures"]) == 0


def test_config_default_batched_translate_range_runs_model_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "batched-default"
    _write_chapter(release_id, 1)
    _write_chapter(release_id, 2)
    calls: list[tuple[str, int]] = []

    def pass1(**kwargs):
        chapter = int(kwargs["chapter_number"])
        calls.append(("pass1", chapter))
        return {"status": "success", "pass1_artifact": f"p1-{chapter}.json"}

    def pass2(**kwargs):
        chapter = int(kwargs["chapter_number"])
        calls.append(("pass2", chapter))
        return {"status": "success", "pass2_artifact": f"p2-{chapter}.json"}

    def pass3(**kwargs):
        chapter = int(kwargs["chapter_number"])
        calls.append(("pass3", chapter))
        return {"status": "success", "pass3_artifact": f"p3-{chapter}.json"}

    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass1", pass1)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass2", pass2)
    monkeypatch.setattr("resemantica.translation.pipeline.translate_chapter_pass3", pass3)

    config = AppConfig(translation=TranslationConfig(batched_model_order=True))
    result = OrchestrationRunner(release_id, "run", config=config).run_stage(
        "translate-range",
        chapter_start=1,
        chapter_end=2,
    )

    assert result.success is True
    assert calls == [
        ("pass1", 1),
        ("pass1", 2),
        ("pass2", 1),
        ("pass2", 2),
        ("pass3", 1),
        ("pass3", 2),
    ]
