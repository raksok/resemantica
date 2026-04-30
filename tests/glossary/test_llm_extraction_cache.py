from __future__ import annotations

import json
from pathlib import Path

from resemantica.glossary.discovery import discover_candidates_from_extracted
from resemantica.llm.prompts import load_prompt
from resemantica.settings import derive_paths, load_config


class CountingGlossaryLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        self.calls += 1
        return self.response


def _write_chapter(paths, number: int) -> None:
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
    block_id = f"ch{number:03d}_blk001"
    payload = {
        "chapter_number": number,
        "chapter_source_hash": f"hash-{number}",
        "records": [
            {
                "block_id": block_id,
                "parent_block_id": block_id,
                "block_order": 1,
                "segment_order": None,
                "source_text_zh": "青云门弟子张三来到青云山。",
            }
        ],
    }
    (paths.extracted_chapters_dir / f"chapter-{number}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def test_extraction_cache_hit_skips_llm_call(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    paths = derive_paths(load_config(), release_id="cache-hit")
    _write_chapter(paths, 1)
    prompt = load_prompt("glossary_discover.txt")
    llm = CountingGlossaryLLM(
        json.dumps(
            {"glossary_terms": [{"source_term": "青云门", "category": "faction"}]},
            ensure_ascii=False,
        )
    )

    first = discover_candidates_from_extracted(
        release_id="cache-hit",
        extracted_chapters_dir=paths.extracted_chapters_dir,
        discovery_run_id="run",
        llm_client=llm,
        model_name="analyst",
        prompt_template=prompt.template,
        prompt_version=prompt.version,
        cache_root=paths.release_root / "cache" / "llm",
    )
    second = discover_candidates_from_extracted(
        release_id="cache-hit",
        extracted_chapters_dir=paths.extracted_chapters_dir,
        discovery_run_id="run",
        llm_client=llm,
        model_name="analyst",
        prompt_template=prompt.template,
        prompt_version=prompt.version,
        cache_root=paths.release_root / "cache" / "llm",
    )

    assert len(first) == 1
    assert len(second) == 1
    assert llm.calls == 1


def test_invalid_cached_extraction_output_is_regenerated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    paths = derive_paths(load_config(), release_id="cache-invalid")
    _write_chapter(paths, 1)
    prompt = load_prompt("glossary_discover.txt")
    invalid = CountingGlossaryLLM("not-json")
    valid = CountingGlossaryLLM(
        json.dumps(
            {"glossary_terms": [{"source_term": "张三", "category": "character"}]},
            ensure_ascii=False,
        )
    )

    first = discover_candidates_from_extracted(
        release_id="cache-invalid",
        extracted_chapters_dir=paths.extracted_chapters_dir,
        discovery_run_id="run",
        llm_client=invalid,
        model_name="analyst",
        prompt_template=prompt.template,
        prompt_version=prompt.version,
        cache_root=paths.release_root / "cache" / "llm",
    )
    second = discover_candidates_from_extracted(
        release_id="cache-invalid",
        extracted_chapters_dir=paths.extracted_chapters_dir,
        discovery_run_id="run",
        llm_client=valid,
        model_name="analyst",
        prompt_template=prompt.template,
        prompt_version=prompt.version,
        cache_root=paths.release_root / "cache" / "llm",
    )

    assert first == []
    assert len(second) == 1
    assert invalid.calls == 1
    assert valid.calls == 1
