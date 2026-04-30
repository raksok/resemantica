from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re

from resemantica.db.idiom_repo import (
    ensure_idiom_schema,
    list_conflicts,
    list_policies,
    promote_policies,
)
from resemantica.db.sqlite import open_connection
from resemantica.idioms.matching import match_idioms
from resemantica.idioms.models import IdiomPolicy
from resemantica.idioms.pipeline import preprocess_idioms, resolve_idiom_policy
from resemantica.idioms.validators import normalize_idiom_source
from resemantica.settings import derive_paths, load_config


class ScriptedIdiomLLM:
    def __init__(self, rows_by_chapter: dict[int, list[dict[str, str]]]) -> None:
        self.rows_by_chapter = rows_by_chapter

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        if "IDIOM_DETECT" in prompt:
            chapter_match = re.search(r"## CHAPTER NUMBER\s+(\d+)", prompt)
            if chapter_match is None:
                raise RuntimeError("chapter number missing from idiom prompt")
            chapter_number = int(chapter_match.group(1))
            return json.dumps({"idioms": self.rows_by_chapter.get(chapter_number, [])}, ensure_ascii=False)
        raise RuntimeError("Unexpected prompt type")


class ScriptedTranslatorLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        return self.response


def _write_extracted_chapter(
    *,
    release_id: str,
    chapter_number: int,
    source_text: str,
) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
    block_id = f"ch{chapter_number:03d}_blk001"
    payload = {
        "chapter_id": f"chapter-{chapter_number}",
        "chapter_number": chapter_number,
        "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
        "chapter_source_hash": f"hash-ch{chapter_number}",
        "schema_version": 1,
        "records": [
            {
                "chapter_id": f"chapter-{chapter_number}",
                "chapter_number": chapter_number,
                "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
                "block_id": block_id,
                "parent_block_id": block_id,
                "segment_id": None,
                "block_order": 1,
                "segment_order": None,
                "source_text_zh": source_text,
                "placeholder_map_ref": "",
                "chapter_source_hash": f"hash-ch{chapter_number}",
                "schema_version": 1,
            }
        ],
    }
    chapter_path = paths.extracted_chapters_dir / f"chapter-{chapter_number}.json"
    chapter_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _insert_policy(
    *,
    release_id: str,
    source_text: str,
    meaning_zh: str,
    preferred_rendering_en: str,
) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        promote_policies(
            conn,
            policies=[
                IdiomPolicy(
                    idiom_id="idi_test_existing",
                    release_id=release_id,
                    source_text=source_text,
                    normalized_source_text=normalize_idiom_source(source_text),
                    meaning_zh=meaning_zh,
                    preferred_rendering_en=preferred_rendering_en,
                    usage_notes=None,
                    policy_status="approved",
                    first_seen_chapter=1,
                    last_seen_chapter=1,
                    appearance_count=1,
                    promoted_from_candidate_id="ican_existing",
                    approval_run_id=f"seed-{datetime.now(UTC).isoformat()}",
                    schema_version=1,
                )
            ],
        )
    finally:
        conn.close()


def test_preprocess_idioms_merges_normalized_duplicates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m5-merge"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="他可谓一箭双雕。",
    )
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=2,
        source_text="这一招真是一箭双雕。",
    )

    llm = ScriptedIdiomLLM(
        {
            1: [
                {
                    "source_text": "一箭双雕",
                    "meaning_zh": "一举两得",
                    "usage_notes": "use for one action with two outcomes",
                }
            ],
            2: [
                {
                    "source_text": "一箭双雕  ",
                    "meaning_zh": "一举两得",
                }
            ],
        }
    )
    translator = ScriptedTranslatorLLM("kill two birds with one stone")
    result = preprocess_idioms(
        release_id=release_id,
        run_id="idioms-001",
        llm_client=llm,
        translator_llm_client=translator,
    )

    assert result["status"] == "success"
    assert result["promoted_count"] == 1
    assert result["conflict_count"] == 0

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        policies = list_policies(conn, release_id=release_id)
        assert len(policies) == 1
        policy = policies[0]
        assert policy.first_seen_chapter == 1
        assert policy.last_seen_chapter == 2
        assert policy.appearance_count >= 2
    finally:
        conn.close()


def test_duplicate_conflict_rejects_policy_promotion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m5-duplicate-conflict"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="他想一箭双雕。",
    )

    llm = ScriptedIdiomLLM(
        {
            1: [
                {
                    "source_text": "一箭双雕",
                    "meaning_zh": "一举两得",
                },
                {
                    "source_text": "一箭双雕",
                    "meaning_zh": "双重好处",
                },
            ]
        }
    )
    translator = ScriptedTranslatorLLM("kill two birds with one stone")
    result = preprocess_idioms(
        release_id=release_id,
        run_id="idioms-001",
        llm_client=llm,
        translator_llm_client=translator,
    )

    assert result["status"] == "success"
    assert result["promoted_count"] == 0
    assert result["conflict_count"] == 2

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        policies = list_policies(conn, release_id=release_id)
        conflicts = list_conflicts(conn, release_id=release_id)
        assert policies == []
        assert all(conflict.conflict_type == "duplicate_conflict" for conflict in conflicts)
    finally:
        conn.close()


def test_existing_policy_conflict_is_recorded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m5-canon-conflict"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="此计可谓一箭双雕。",
    )
    _insert_policy(
        release_id=release_id,
        source_text="一箭双雕",
        meaning_zh="一举两得",
        preferred_rendering_en="kill two birds with one stone",
    )

    llm = ScriptedIdiomLLM(
        {
            1: [
                {
                    "source_text": "一箭双雕",
                    "meaning_zh": "一举两得",
                }
            ]
        }
    )
    translator = ScriptedTranslatorLLM("one move, two wins")
    result = preprocess_idioms(
        release_id=release_id,
        run_id="idioms-001",
        llm_client=llm,
        translator_llm_client=translator,
    )

    assert result["status"] == "success"
    assert result["promoted_count"] == 0
    assert result["conflict_count"] == 1

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        conflicts = list_conflicts(conn, release_id=release_id)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == "canon_conflict"
    finally:
        conn.close()


def test_exact_match_precedence_hook_uses_locked_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m5-precedence"
    _insert_policy(
        release_id=release_id,
        source_text="一箭双雕",
        meaning_zh="一举两得",
        preferred_rendering_en="kill two birds with one stone",
    )

    resolved = resolve_idiom_policy(
        release_id=release_id,
        source_text="一箭双雕",
        fallback_rendering="fuzzy fallback",
    )
    assert resolved == "kill two birds with one stone"

    missing = resolve_idiom_policy(
        release_id=release_id,
        source_text="杯弓蛇影",
        fallback_rendering="fuzzy fallback",
    )
    assert missing == "fuzzy fallback"

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        matched = match_idioms(text="他这招可谓一箭双雕。", idiom_policies=list_policies(conn, release_id=release_id))
        assert len(matched) == 1
        assert matched[0].source_text == "一箭双雕"
    finally:
        conn.close()

