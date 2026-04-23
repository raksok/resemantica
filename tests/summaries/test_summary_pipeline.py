from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re

import pytest

from resemantica.db.glossary_repo import ensure_glossary_schema, promote_locked_entries
from resemantica.db.sqlite import open_connection
from resemantica.db.summary_repo import (
    ensure_summary_schema,
    get_validated_summary,
    list_derived_summaries,
)
from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.glossary.validators import normalize_term
from resemantica.settings import derive_paths, load_config
from resemantica.summaries.pipeline import preprocess_summaries


class ScriptedSummaryLLM:
    def __init__(self, structured_by_chapter: dict[int, dict[str, object]]) -> None:
        self.structured_by_chapter = structured_by_chapter

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        if "SUMMARY_ZH_STRUCTURED" in prompt:
            chapter_match = re.search(r"## CHAPTER NUMBER\s+(\d+)", prompt)
            if chapter_match is None:
                raise RuntimeError("chapter number missing from prompt")
            chapter_number = int(chapter_match.group(1))
            return json.dumps(self.structured_by_chapter[chapter_number], ensure_ascii=False)

        if "SUMMARY_EN_DERIVE" in prompt:
            source_match = re.search(r"## SOURCE TEXT \(ZH\)\s+(.+?)\s+## INSTRUCTIONS", prompt, re.S)
            source = "" if source_match is None else source_match.group(1).strip()
            return f"EN::{source}"

        raise RuntimeError("Unexpected prompt")


def _write_extracted_chapter(
    *,
    release_id: str,
    chapter_number: int,
    source_text: str,
    chapter_source_hash: str,
) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)

    block_id = f"ch{chapter_number:03d}_blk001"
    payload = {
        "chapter_id": f"chapter-{chapter_number}",
        "chapter_number": chapter_number,
        "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
        "chapter_source_hash": chapter_source_hash,
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
                "placeholder_map_ref": str(
                    (paths.extracted_placeholders_dir / f"chapter-{chapter_number}.json").as_posix()
                ),
                "chapter_source_hash": chapter_source_hash,
                "schema_version": 1,
            }
        ],
    }
    chapter_path = paths.extracted_chapters_dir / f"chapter-{chapter_number}.json"
    chapter_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _insert_locked_glossary_term(
    *,
    release_id: str,
    source_term: str,
    target_term: str,
    category: str,
) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        promote_locked_entries(
            conn,
            entries=[
                LockedGlossaryEntry(
                    glossary_entry_id="glex_summary_test",
                    release_id=release_id,
                    source_term=source_term,
                    normalized_source_term=normalize_term(source_term),
                    target_term=target_term,
                    normalized_target_term=normalize_term(target_term),
                    category=category,
                    status="approved",
                    approved_at=datetime.now(UTC).isoformat(),
                    approval_run_id="promote-001",
                    source_candidate_id="gcan_summary_test",
                    schema_version=1,
                )
            ],
        )
    finally:
        conn.close()


def test_preprocess_summaries_materializes_authority_and_derived_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m4-success"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三来到青云山。",
        chapter_source_hash="hash-ch1",
    )
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=2,
        source_text="张三通过试炼。",
        chapter_source_hash="hash-ch2",
    )

    llm = ScriptedSummaryLLM(
        {
            1: {
                "chapter_number": 1,
                "characters_mentioned": ["张三"],
                "key_events": ["张三来到青云山"],
                "new_terms": ["青云山"],
                "relationships_changed": [{"entity": "张三", "change": "entered 青云山"}],
                "setting": "青云山",
                "tone": "calm",
                "narrative_progression": "张三初入山门。",
            },
            2: {
                "chapter_number": 2,
                "characters_mentioned": ["张三"],
                "key_events": ["张三通过试炼"],
                "new_terms": ["入门试炼"],
                "relationships_changed": [{"entity": "张三", "change": "passed trial"}],
                "setting": "青云山",
                "tone": "tense",
                "narrative_progression": "张三完成第一次试炼。",
            },
        }
    )

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )
    assert result["status"] == "success"
    assert result["chapters_processed"] == 2

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        chapter2_story = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=2,
            summary_type="story_so_far_zh",
        )
        assert chapter2_story is not None
        assert chapter2_story.content_zh == "第1章：张三初入山门。\n第2章：张三完成第一次试炼。"

        chapter2_short = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=2,
            summary_type="chapter_summary_zh_short",
        )
        assert chapter2_short is not None
        assert chapter2_short.content_zh == "张三完成第一次试炼。"

        derived = list_derived_summaries(conn, release_id=release_id, chapter_number=2)
        assert len(derived) == 2
        for row in derived:
            assert row.source_summary_hash
            assert row.glossary_version_hash
    finally:
        conn.close()


def test_glossary_conflict_blocks_chinese_summary_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m4-glossary-conflict"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="青云门收徒。",
        chapter_source_hash="hash-ch1",
    )
    _insert_locked_glossary_term(
        release_id=release_id,
        source_term="青云门",
        target_term="Azure Sect",
        category="faction",
    )

    llm = ScriptedSummaryLLM(
        {
            1: {
                "chapter_number": 1,
                "characters_mentioned": ["张三"],
                "key_events": ["Azure Sect收徒"],
                "new_terms": ["Azure Sect"],
                "relationships_changed": [{"entity": "张三", "change": "joined Azure Sect"}],
                "setting": "青云山",
                "tone": "formal",
                "narrative_progression": "张三加入Azure Sect。",
            }
        }
    )

    with pytest.raises(RuntimeError, match="glossary_conflict"):
        preprocess_summaries(
            release_id=release_id,
            run_id="summaries-001",
            llm_client=llm,
        )


def test_future_knowledge_leak_fails_validation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m4-future-knowledge"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三开始修炼。",
        chapter_source_hash="hash-ch1",
    )

    llm = ScriptedSummaryLLM(
        {
            1: {
                "chapter_number": 1,
                "characters_mentioned": ["张三"],
                "key_events": ["第3章张三成为宗主"],
                "new_terms": ["宗主"],
                "relationships_changed": [{"entity": "张三", "change": "will become leader in 第3章"}],
                "setting": "青云山",
                "tone": "ominous",
                "narrative_progression": "他在第3章达到巅峰。",
            }
        }
    )

    with pytest.raises(RuntimeError, match="future_knowledge"):
        preprocess_summaries(
            release_id=release_id,
            run_id="summaries-001",
            llm_client=llm,
        )


def test_continuity_conflict_on_chapter_number_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m4-continuity"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三上山。",
        chapter_source_hash="hash-ch1",
    )

    llm = ScriptedSummaryLLM(
        {
            1: {
                "chapter_number": 2,
                "characters_mentioned": ["张三"],
                "key_events": ["张三上山"],
                "new_terms": ["青云山"],
                "relationships_changed": [{"entity": "张三", "change": "arrived"}],
                "setting": "青云山",
                "tone": "steady",
                "narrative_progression": "张三开始旅程。",
            }
        }
    )

    with pytest.raises(RuntimeError, match="continuity_conflict"):
        preprocess_summaries(
            release_id=release_id,
            run_id="summaries-001",
            llm_client=llm,
        )


def test_story_so_far_rebuild_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m4-deterministic"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="第一章内容。",
        chapter_source_hash="hash-ch1",
    )
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=2,
        source_text="第二章内容。",
        chapter_source_hash="hash-ch2",
    )

    llm = ScriptedSummaryLLM(
        {
            1: {
                "chapter_number": 1,
                "characters_mentioned": ["甲"],
                "key_events": ["甲出场"],
                "new_terms": ["甲"],
                "relationships_changed": [{"entity": "甲", "change": "introduced"}],
                "setting": "城镇",
                "tone": "neutral",
                "narrative_progression": "甲在城镇露面。",
            },
            2: {
                "chapter_number": 2,
                "characters_mentioned": ["甲"],
                "key_events": ["甲离开城镇"],
                "new_terms": ["路途"],
                "relationships_changed": [{"entity": "甲", "change": "departed"}],
                "setting": "山道",
                "tone": "urgent",
                "narrative_progression": "甲离开城镇踏上山道。",
            },
        }
    )

    preprocess_summaries(release_id=release_id, run_id="summaries-001", llm_client=llm)

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        first_story = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=2,
            summary_type="story_so_far_zh",
        )
        assert first_story is not None
        first_content = first_story.content_zh
    finally:
        conn.close()

    preprocess_summaries(release_id=release_id, run_id="summaries-002", llm_client=llm)

    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        second_story = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=2,
            summary_type="story_so_far_zh",
        )
        assert second_story is not None
        assert second_story.content_zh == first_content
    finally:
        conn.close()
