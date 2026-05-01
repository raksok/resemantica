from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

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
    def __init__(
        self,
        structured_by_chapter: dict[int, dict[str, object]],
        validation_flags: dict[int, list[str]] | None = None,
    ) -> None:
        self.structured_by_chapter = structured_by_chapter
        self.validation_flags = validation_flags or {}

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

        if "SUMMARY_ZH_VALIDATE" in prompt:
            chapter_match = re.search(r"## CHAPTER NUMBER\s+(\d+)", prompt)
            chapter_number = int(chapter_match.group(1)) if chapter_match else 0
            flags = self.validation_flags.get(chapter_number, [])
            return json.dumps({"flags": flags, "warnings": []}, ensure_ascii=False)

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
                "is_story_chapter": True,
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
                "is_story_chapter": True,
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
        expected_composite = hashlib.sha256(b"hash-ch1|hash-ch2").hexdigest()
        assert chapter2_story.derived_from_chapter_hash == expected_composite

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


def test_preprocess_summaries_emits_progress_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m19-summary-events"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三来到青云山。",
        chapter_source_hash="hash-ch1",
    )
    llm = ScriptedSummaryLLM(
        {
            1: {
                "chapter_number": 1,
                "characters_mentioned": ["张三"],
                "key_events": ["张三来到青云山"],
                "new_terms": ["青云山"],
                "relationships_changed": [{"entity": "张三", "change": "entered"}],
                "setting": "青云山",
                "tone": "calm",
                "narrative_progression": "张三初入山门。",
                "is_story_chapter": True,
            }
        }
    )
    from resemantica.orchestration.events import subscribe, unsubscribe

    received = []

    def callback(event):
        if event.run_id == "summaries-events":
            received.append(event)

    subscribe("*", callback)
    try:
        preprocess_summaries(
            release_id=release_id,
            run_id="summaries-events",
            llm_client=llm,
        )
    finally:
        unsubscribe("*", callback)

    event_types = [event.event_type for event in received]
    assert event_types == [
        "preprocess-summaries.started",
        "preprocess-summaries.chapter_started",
        "preprocess-summaries.draft_generated",
        "preprocess-summaries.validation_completed",
        "preprocess-summaries.chapter_completed",
        "preprocess-summaries.completed",
    ]
    assert received[0].payload["total_chapters"] == 1
    assert received[1].chapter_number == 1
    assert received[-1].payload["done"] == 1


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
                "is_story_chapter": True,
            }
        }
    )

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )
    assert result["status"] == "success"
    assert result["chapters_processed"] == 0


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
                "is_story_chapter": True,
            }
        }
    )

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )
    assert result["status"] == "success"
    assert result["chapters_processed"] == 0


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
                "is_story_chapter": True,
            }
        }
    )

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )
    assert result["status"] == "success"
    assert result["chapters_processed"] == 0


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
                "is_story_chapter": True,
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
                "is_story_chapter": True,
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


def test_chapter_exclusion_patterns(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m4-exclude"
    for i in [1, 2, 3]:
        doc = f"OEBPS/chapter{i}.xhtml" if i != 2 else "OEBPS/titlepage.xhtml"
        _write_extracted_chapter(
            release_id=release_id,
            chapter_number=i,
            source_text=f"内容{i}。" if i != 2 else "书名页。",
            chapter_source_hash=f"hash-ch{i}",
        )
        if i == 2:
            chapter_path = (
                derive_paths(load_config(), release_id=release_id).extracted_chapters_dir
                / f"chapter-{i}.json"
            )
            payload = json.loads(chapter_path.read_text(encoding="utf-8"))
            payload["source_document_path"] = doc
            chapter_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )

    llm = ScriptedSummaryLLM(
        {
            i: {
                "chapter_number": i,
                "characters_mentioned": ["甲"],
                "key_events": [f"事件{i}"],
                "new_terms": [],
                "relationships_changed": [],
                "setting": "城镇",
                "tone": "neutral",
                "narrative_progression": f"进展{i}。",
                "is_story_chapter": True,
            }
            for i in [1, 3]
        }
    )

    cfg = load_config()
    cfg.summaries.exclude_chapter_patterns = ["titlepage"]
    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
        config=cfg,
    )
    assert result["status"] == "success"
    assert result["chapters_processed"] == 2
    skipped = [r for r in result["chapter_artifacts"] if r.get("status") == "skipped"]
    assert len(skipped) == 1
    assert skipped[0]["chapter_number"] == 2


def test_llm_validation_flags_in_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m4-flags"
    for i in [1, 2]:
        _write_extracted_chapter(
            release_id=release_id,
            chapter_number=i,
            source_text=f"第{i}章内容。",
            chapter_source_hash=f"hash-ch{i}",
        )

    llm = ScriptedSummaryLLM(
        {
            1: {
                "chapter_number": 1,
                "characters_mentioned": ["甲"],
                "key_events": ["甲出场"],
                "new_terms": [],
                "relationships_changed": [],
                "setting": "山镇",
                "tone": "quiet",
                "narrative_progression": "甲在山镇出现。",
                "is_story_chapter": True,
            },
            2: {
                "chapter_number": 2,
                "characters_mentioned": ["甲"],
                "key_events": ["甲离开"],
                "new_terms": [],
                "relationships_changed": [],
                "setting": "山路",
                "tone": "urgent",
                "narrative_progression": "甲踏上路程。",
                "is_story_chapter": True,
            },
        },
        validation_flags={1: ["unsupported_claim"]},
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
    zh_artifact = paths.summaries_dir / "chapter-1-zh.json"
    assert zh_artifact.exists()
    data = json.loads(zh_artifact.read_text(encoding="utf-8"))
    assert "llm_validation_flags" in data
    assert data["llm_validation_flags"] == ["unsupported_claim"]


def test_non_story_chapter_validator_flagged() -> None:
    from resemantica.summaries.validators import validate_chinese_summary

    non_story_summary = {
        "chapter_number": 0,
        "characters_mentioned": [],
        "key_events": [],
        "new_terms": [],
        "relationships_changed": [],
        "setting": "",
        "tone": "",
        "narrative_progression": "Non-story chapter: Copyright page",
        "is_story_chapter": False,
    }
    result = validate_chinese_summary(
        structured_summary=non_story_summary,
        expected_chapter_number=0,
        locked_glossary=[],
    )
    assert result.is_valid is False
    assert "non_story_chapter_flagged" in result.errors


def test_non_story_chapter_pipeline_skipped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m4-non-story"

    for i in [1, 2, 3]:
        source = f"第{i}章内容。" if i != 2 else "版权所有 © 2024 作者名。未经许可，不得转载。"
        _write_extracted_chapter(
            release_id=release_id,
            chapter_number=i,
            source_text=source,
            chapter_source_hash=f"hash-ch{i}",
        )

    llm_responses = {
        1: {
            "chapter_number": 1,
            "characters_mentioned": ["甲"],
            "key_events": ["事件1"],
            "new_terms": [],
            "relationships_changed": [],
            "setting": "城镇",
            "tone": "neutral",
            "narrative_progression": "进展1。",
            "is_story_chapter": True,
        },
        2: {
            "chapter_number": 2,
            "characters_mentioned": [],
            "key_events": [],
            "new_terms": [],
            "relationships_changed": [],
            "setting": "",
            "tone": "",
            "narrative_progression": "Non-story chapter: Copyright page",
            "is_story_chapter": False,
        },
        3: {
            "chapter_number": 3,
            "characters_mentioned": ["乙"],
            "key_events": ["事件3"],
            "new_terms": [],
            "relationships_changed": [],
            "setting": "山林",
            "tone": "mysterious",
            "narrative_progression": "进展3。",
            "is_story_chapter": True,
        },
    }

    class NonStoryScriptedLLM:
        def generate_text(self, *, model_name: str, prompt: str) -> str:
            if "SUMMARY_ZH_STRUCTURED" in prompt:
                chapter_match = re.search(r"## CHAPTER NUMBER\s+(\d+)", prompt)
                if chapter_match is None:
                    raise RuntimeError("chapter number missing from prompt")
                chapter_number = int(chapter_match.group(1))
                return json.dumps(llm_responses[chapter_number], ensure_ascii=False)
            if "SUMMARY_EN_DERIVE" in prompt:
                return "EN::content"
            if "SUMMARY_ZH_VALIDATE" in prompt:
                return json.dumps({"flags": [], "warnings": []}, ensure_ascii=False)
            raise RuntimeError("Unexpected prompt")

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=NonStoryScriptedLLM(),
    )
    assert result["status"] == "success"
    assert result["chapters_processed"] == 2

    skipped = [r for r in result["chapter_artifacts"] if r.get("status") == "skipped"]
    assert len(skipped) == 1
    assert skipped[0]["chapter_number"] == 2
    assert skipped[0]["reason"] == "non_story_chapter"

    processed = [r for r in result["chapter_artifacts"] if r.get("status") != "skipped"]
    assert len(processed) == 2
    assert {r["chapter_number"] for r in processed} == {1, 3}
