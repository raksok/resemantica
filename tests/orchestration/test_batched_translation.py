from __future__ import annotations

import json
from pathlib import Path

from resemantica.orchestration.runner import OrchestrationRunner
from resemantica.settings import derive_paths, load_config


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
    assert result.checkpoint["pass1_completed"] == [1, 2]
