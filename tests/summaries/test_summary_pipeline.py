from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from resemantica.db.glossary_repo import ensure_glossary_schema, promote_locked_entries
from resemantica.db.sqlite import open_connection
from resemantica.db.summary_repo import (
    ensure_summary_schema,
    get_summary_checkpoint,
    get_validated_summary,
    list_derived_summaries,
    set_summary_checkpoint,
)
from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.glossary.validators import normalize_term
from resemantica.settings import derive_paths, load_config
from resemantica.summaries.pipeline import preprocess_summaries
from resemantica.tracking.repo import ensure_tracking_db, load_events


class ScriptedSummaryLLM:
    def __init__(
        self,
        structured_by_chapter: dict[int, dict[str, object]],
        validation_flags: dict[int, list[str]] | None = None,
        validation_warnings: dict[int, list[str]] | None = None,
        fenced_validation_json: bool = False,
    ) -> None:
        self.structured_by_chapter = structured_by_chapter
        self.validation_flags = validation_flags or {}
        self.validation_warnings = validation_warnings or {}
        self.fenced_validation_json = fenced_validation_json
        self.validation_prompts: list[str] = []

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        if "SUMMARY_ZH_STRUCTURED" in prompt:
            chapter_match = re.search(r"## CHAPTER NUMBER\s+(\d+)", prompt)
            if chapter_match is None:
                raise RuntimeError("chapter number missing from prompt")
            chapter_number = int(chapter_match.group(1))
            return json.dumps(self.structured_by_chapter[chapter_number], ensure_ascii=False)

        if "SUMMARY_EN_DERIVE" in prompt:
            source_match = re.search(r"## SOURCE TEXT \(ZH\)\s+(.+?)\s+## INSTRUCTIONS", prompt, re.S)
            if source_match is not None:
                source = source_match.group(1).strip()
            else:
                source = prompt.rsplit("no addintional explanation:", maxsplit=1)[-1].strip()
            return f"EN::{source}"

        if "SUMMARY_STORY_COMPACT" in prompt:
            previous_match = re.search(
                r"## PREVIOUS STORY SO FAR ZH COMPACT\s*(.*?)\s*## CURRENT CHAPTER SUMMARY ZH SHORT",
                prompt,
                re.S,
            )
            current_match = re.search(
                r"## CURRENT CHAPTER SUMMARY ZH SHORT\s*(.*?)\s*## TOKEN BUDGET",
                prompt,
                re.S,
            )
            previous = "" if previous_match is None else previous_match.group(1).strip()
            current = "" if current_match is None else current_match.group(1).strip()
            return "\n".join(part for part in [previous, current] if part)

        if "SUMMARY_ZH_VALIDATE" in prompt:
            self.validation_prompts.append(prompt)
            chapter_match = re.search(r"## CHAPTER NUMBER\s+(\d+)", prompt)
            chapter_number = int(chapter_match.group(1)) if chapter_match else 0
            flags = self.validation_flags.get(chapter_number, [])
            warnings = self.validation_warnings.get(chapter_number, [])
            payload = json.dumps({"flags": flags, "warnings": warnings}, ensure_ascii=False)
            if self.fenced_validation_json:
                return f"```json\n{payload}\n```"
            return payload

        raise RuntimeError("Unexpected prompt")


def _structured_summary_payload(
    *,
    chapter_number: int = 1,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "chapter_number": chapter_number,
        "characters_mentioned": ["张三"],
        "key_events": ["张三开始修炼"],
        "new_terms": [],
        "relationships_changed": [{"entity": "张三", "change": "开始修炼"}],
        "setting": "山中",
        "tone": "calm",
        "narrative_progression": "张三开始修炼。",
        "is_story_chapter": True,
    }
    payload.update(overrides)
    return payload


class SequencedSummaryLLM:
    def __init__(self, structured_responses: list[dict[str, object] | str]) -> None:
        self.structured_responses = structured_responses
        self.prompts: list[str] = []
        self._last_structured: dict[str, object] | None = None

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        if "SUMMARY_ZH_STRUCTURED" in prompt:
            self.prompts.append(prompt)
            index = min(len(self.prompts) - 1, len(self.structured_responses) - 1)
            response = self.structured_responses[index]
            if isinstance(response, str):
                return response
            self._last_structured = response
            return json.dumps(response, ensure_ascii=False)

        if "SUMMARY_STORY_COMPACT" in prompt:
            if self._last_structured is None:
                return "张三开始修炼。"
            return str(self._last_structured.get("narrative_progression", "张三开始修炼。"))

        if "SUMMARY_EN_DERIVE" in prompt:
            return "EN::content"

        if "SUMMARY_ZH_VALIDATE" in prompt:
            return json.dumps({"flags": [], "warnings": []}, ensure_ascii=False)

        raise RuntimeError("Unexpected prompt")


def _write_extracted_chapter(
    *,
    release_id: str,
    chapter_number: int,
    source_text: str,
    chapter_source_hash: str,
    source_document_path: str | None = None,
) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)

    block_id = f"ch{chapter_number:03d}_blk001"
    source_path = source_document_path or f"OEBPS/chapter{chapter_number}.xhtml"
    payload = {
        "chapter_id": f"chapter-{chapter_number}",
        "chapter_number": chapter_number,
        "source_document_path": source_path,
        "chapter_source_hash": chapter_source_hash,
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
        chapter2_compact = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=2,
            summary_type="story_so_far_zh_compact",
        )
        assert chapter2_compact is not None
        assert chapter2_compact.content_zh == "张三初入山门。\n张三完成第一次试炼。"

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
        story_en = next(row for row in derived if row.summary_type == "story_so_far_en")
        assert story_en.source_summary_id == chapter2_compact.summary_id
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
    expected_progress = [
        "preprocess-summaries.started",
        "preprocess-summaries.chapter_started",
        "preprocess-summaries.draft_generated",
        "preprocess-summaries.validation_completed",
        "preprocess-summaries.chapter_completed",
        "preprocess-summaries.completed",
    ]
    positions = [event_types.index(event_type) for event_type in expected_progress]
    assert positions == sorted(positions)
    assert "preprocess-summaries.generation_started" in event_types
    assert "preprocess-summaries.generation_completed" in event_types
    assert "preprocess-summaries.llm_validation_started" in event_types
    assert "preprocess-summaries.llm_validation_completed" in event_types
    assert "preprocess-summaries.english_derivation_started" in event_types
    assert "preprocess-summaries.english_derivation_completed" in event_types
    assert received[0].payload["total_chapters"] == 1
    assert received[1].chapter_number == 1
    assert received[-1].payload["done"] == 1


def test_glossary_conflict_does_not_block_chinese_summary_validation(
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
    assert result["chapters_processed"] == 1


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
    assert result["status"] == "failed"
    assert result["chapters_processed"] == 0
    assert result["failed_chapters"] == [1]
    assert result["failure_reasons"]["1"] == "future_knowledge_failed"

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        cp = get_summary_checkpoint(conn, release_id=release_id, run_id="summaries-001")
        assert cp is None or cp[0] == 0
        row = conn.execute(
            "SELECT validation_status, content_json FROM summary_drafts "
            "WHERE release_id = ? AND chapter_number = 1",
            (release_id,),
        ).fetchone()
        assert row is not None
        assert row["validation_status"] == "failed"
        content = json.loads(row["content_json"])
        assert content["failure_category"] == "future_knowledge_failed"
    finally:
        conn.close()


def test_summary_generation_retries_with_reason_only_feedback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m52-summary-retry"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三开始修炼。",
        chapter_source_hash="hash-ch1",
    )

    prompts: list[str] = []

    class RetryLLM:
        def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
            if "SUMMARY_ZH_STRUCTURED" in prompt:
                prompts.append(prompt)
                if len(prompts) == 1:
                    return "{not-json"
                assert "Failure category: parse_failed" in prompt
                assert "{not-json" not in prompt
                return json.dumps(
                    {
                        "chapter_number": 1,
                        "characters_mentioned": ["张三"],
                        "key_events": ["张三开始修炼"],
                        "new_terms": [],
                        "relationships_changed": [{"entity": "张三", "change": "开始修炼"}],
                        "setting": "山中",
                        "tone": "calm",
                        "narrative_progression": "张三开始修炼。",
                        "is_story_chapter": True,
                    },
                    ensure_ascii=False,
                )
            if "SUMMARY_STORY_COMPACT" in prompt:
                return "张三开始修炼。"
            if "SUMMARY_EN_DERIVE" in prompt:
                return "EN::content"
            if "SUMMARY_ZH_VALIDATE" in prompt:
                return json.dumps({"flags": [], "warnings": []}, ensure_ascii=False)
            raise RuntimeError("Unexpected prompt")

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=RetryLLM(),
    )

    assert result["status"] == "success"
    assert result["chapters_processed"] == 1
    assert len(prompts) == 2


def test_summary_schema_retry_success_for_missing_story_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m54-missing-story-retry"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三开始修炼。",
        chapter_source_hash="hash-ch1",
    )
    first = _structured_summary_payload()
    first.pop("is_story_chapter")
    llm = SequencedSummaryLLM([first, _structured_summary_payload()])

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )

    assert result["status"] == "success"
    assert len(llm.prompts) == 2
    assert 'Add "is_story_chapter" as literal true or false.' in llm.prompts[1]


def test_summary_schema_recovers_missing_story_flag_after_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m54-missing-story-default"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三开始修炼。",
        chapter_source_hash="hash-ch1",
    )
    missing = _structured_summary_payload()
    missing.pop("is_story_chapter")
    llm = SequencedSummaryLLM([missing, dict(missing)])

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )

    assert result["status"] == "success"
    assert result["chapter_artifacts"][0]["warnings"] == [
        "missing_is_story_chapter_defaulted_true"
    ]
    paths = derive_paths(load_config(), release_id=release_id)
    payload = json.loads((paths.summaries_dir / "chapter-1-zh.json").read_text(encoding="utf-8"))
    structured = json.loads(payload["validated"]["chapter_summary_zh_structured"]["content_zh"])
    assert structured["is_story_chapter"] is True
    assert payload["warnings"] == ["missing_is_story_chapter_defaulted_true"]


def test_summary_schema_retry_success_for_relationship_entries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m54-relationships-retry"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三开始修炼。",
        chapter_source_hash="hash-ch1",
    )
    malformed = _structured_summary_payload(relationships_changed=["张三开始修炼"])
    llm = SequencedSummaryLLM([malformed, _structured_summary_payload()])

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )

    assert result["status"] == "success"
    assert len(llm.prompts) == 2
    assert 'Use only relationships_changed objects: {"entity":"...","change":"..."}.' in llm.prompts[1]


def test_summary_schema_drops_malformed_relationship_entries_after_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m54-relationships-drop"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三开始修炼。",
        chapter_source_hash="hash-ch1",
    )
    malformed = _structured_summary_payload(
        relationships_changed=[
            {"entity": "张三", "change": "开始修炼"},
            "张三开始修炼",
            {"entity": "", "change": "缺少对象"},
            {"entity": "李四", "change": ""},
        ]
    )
    llm = SequencedSummaryLLM([malformed, json.loads(json.dumps(malformed, ensure_ascii=False))])

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )

    assert result["status"] == "success"
    assert result["chapter_artifacts"][0]["warnings"] == [
        "invalid_relationships_changed_entries_dropped"
    ]
    paths = derive_paths(load_config(), release_id=release_id)
    payload = json.loads((paths.summaries_dir / "chapter-1-zh.json").read_text(encoding="utf-8"))
    structured = json.loads(payload["validated"]["chapter_summary_zh_structured"]["content_zh"])
    assert structured["relationships_changed"] == [{"entity": "张三", "change": "开始修炼"}]


def test_summary_schema_retry_success_for_empty_setting_and_tone(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m54-setting-tone-retry"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三开始修炼。",
        chapter_source_hash="hash-ch1",
    )
    empty_fields = _structured_summary_payload(setting="", tone="")
    llm = SequencedSummaryLLM([empty_fields, _structured_summary_payload()])

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )

    assert result["status"] == "success"
    assert len(llm.prompts) == 2
    assert '"setting" must be a short non-empty string.' in llm.prompts[1]
    assert '"tone" must be a short non-empty string.' in llm.prompts[1]


def test_summary_schema_defaults_empty_setting_and_tone_after_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m54-setting-tone-default"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三开始修炼。",
        chapter_source_hash="hash-ch1",
    )
    empty_fields = _structured_summary_payload(setting="", tone="")
    llm = SequencedSummaryLLM([empty_fields, _structured_summary_payload(setting="", tone="")])

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )

    assert result["status"] == "success"
    assert result["chapter_artifacts"][0]["warnings"] == [
        "empty_setting_or_tone_defaulted"
    ]
    paths = derive_paths(load_config(), release_id=release_id)
    payload = json.loads((paths.summaries_dir / "chapter-1-zh.json").read_text(encoding="utf-8"))
    structured = json.loads(payload["validated"]["chapter_summary_zh_structured"]["content_zh"])
    assert structured["setting"] == "未明确"
    assert structured["tone"] == "未明确"


def test_summary_schema_recovery_skips_mixed_unrecoverable_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m54-mixed-hard-fail"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三开始修炼。",
        chapter_source_hash="hash-ch1",
    )
    mixed = _structured_summary_payload()
    mixed.pop("is_story_chapter")
    mixed.pop("narrative_progression")
    llm = SequencedSummaryLLM([mixed])

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )

    assert result["status"] == "failed"
    assert result["failed_chapters"] == [1]
    assert len(llm.prompts) == 4
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        row = conn.execute(
            "SELECT content_json FROM summary_drafts "
            "WHERE release_id = ? AND chapter_number = 1",
            (release_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    content = json.loads(row["content_json"])
    parsed_summary = content["parsed_summary"]
    assert "is_story_chapter" not in parsed_summary
    assert "narrative_progression" not in parsed_summary
    assert "warnings" not in content


def test_summary_structured_prompt_schema_regression() -> None:
    from resemantica.llm.prompts import load_prompt

    prompt = load_prompt("summary_zh_structured.txt")

    assert prompt.version == "1.6"
    for key in [
        "chapter_number",
        "characters_mentioned",
        "key_events",
        "new_terms",
        "relationships_changed",
        "setting",
        "tone",
        "narrative_progression",
        "is_story_chapter",
    ]:
        assert f"- {key}" in prompt.template
    assert "is_story_chapter must be a JSON boolean" in prompt.template
    assert '"relationships_changed": [{{"entity": "张三", "change": "与李四结盟"}}]' in prompt.template
    assert '{{"entity": "张三", "change": "发现李四身份"}}' in prompt.template


def test_exhausted_summary_failure_stops_story_assembly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m52-summary-hard-fail"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三开始修炼。",
        chapter_source_hash="hash-ch1",
    )
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=2,
        source_text="李四来到山门。",
        chapter_source_hash="hash-ch2",
    )

    class BrokenChapterLLM(ScriptedSummaryLLM):
        def generate_text(self, *, model_name: str, prompt: str) -> str:
            if "SUMMARY_ZH_STRUCTURED" in prompt and "## CHAPTER NUMBER\n1" in prompt:
                return "{not-json"
            return super().generate_text(model_name=model_name, prompt=prompt)

    llm = BrokenChapterLLM(
        {
            2: {
                "chapter_number": 2,
                "characters_mentioned": ["李四"],
                "key_events": ["李四来到山门"],
                "new_terms": [],
                "relationships_changed": [{"entity": "李四", "change": "arrived"}],
                "setting": "山门",
                "tone": "quiet",
                "narrative_progression": "李四来到山门。",
                "is_story_chapter": True,
            }
        }
    )

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )

    assert result["status"] == "failed"
    assert result["failed_chapters"] == [1]
    paths = derive_paths(load_config(), release_id=release_id)
    assert not (paths.summaries_dir / "chapter-2-zh.json").exists()


def test_summary_chapter_number_mismatch_is_normalized_with_warning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m44-normalize-summary-id"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=12,
        source_text="第4章 错位标题\n张三抵达青云山。",
        chapter_source_hash="hash-ch12",
        source_document_path="OEBPS/chapter012.xhtml",
    )

    llm = ScriptedSummaryLLM(
        {
            12: {
                "chapter_number": 4,
                "characters_mentioned": ["张三"],
                "key_events": ["张三抵达青云山"],
                "new_terms": ["青云山"],
                "relationships_changed": [{"entity": "张三", "change": "arrived"}],
                "setting": "青云山",
                "tone": "steady",
                "narrative_progression": "第4章：张三抵达青云山。",
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
    assert result["chapters_processed"] == 1
    assert result["chapter_artifacts"][0]["chapter_number"] == 12
    warnings = result["chapter_artifacts"][0]["warnings"]
    assert any("summary_chapter_number_mismatch" in warning for warning in warnings)
    assert any("source_heading_chapter_mismatch" in warning for warning in warnings)

    paths = derive_paths(load_config(), release_id=release_id)
    zh_artifact = paths.summaries_dir / "chapter-12-zh.json"
    payload = json.loads(zh_artifact.read_text(encoding="utf-8"))
    assert payload["warnings"] == warnings
    structured = json.loads(payload["validated"]["chapter_summary_zh_structured"]["content_zh"])
    assert structured["chapter_number"] == 12

    conn = ensure_tracking_db(release_id)
    try:
        events = load_events(conn, run_id="summaries-001", release_id=release_id, limit=20)
    finally:
        conn.close()
    warning_events = [
        event for event in events
        if event.event_type == "preprocess-summaries.chapter_identity_warning"
    ]
    assert warning_events
    assert warning_events[0].chapter_number == 12
    assert warning_events[0].message
    assert "Chapter 12 identity warning:" in warning_events[0].message


def test_visible_source_heading_is_allowed_in_summary_future_check(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m44-visible-heading"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=4,
        source_text="第12章 错位标题\n张三闭关修炼。",
        chapter_source_hash="hash-ch4",
        source_document_path="OEBPS/chapter004.xhtml",
    )

    llm = ScriptedSummaryLLM(
        {
            4: {
                "chapter_number": 4,
                "characters_mentioned": ["张三"],
                "key_events": ["第12章张三闭关修炼"],
                "new_terms": [],
                "relationships_changed": [{"entity": "张三", "change": "trains in 第12章"}],
                "setting": "洞府",
                "tone": "focused",
                "narrative_progression": "第12章：张三闭关修炼。",
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
    assert result["chapters_processed"] == 1
    assert any(
        "source_heading_chapter_mismatch" in warning
        for warning in result["chapter_artifacts"][0]["warnings"]
    )


def test_llm_validation_fenced_json_and_warnings_are_non_blocking(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m44-validation-warning"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=13,
        source_text="Chapter 1\n张三在小镇醒来。",
        chapter_source_hash="hash-ch13",
        source_document_path="OEBPS/chapter013.xhtml",
    )

    llm = ScriptedSummaryLLM(
        {
            13: {
                "chapter_number": 13,
                "characters_mentioned": ["张三"],
                "key_events": ["张三在小镇醒来"],
                "new_terms": ["小镇"],
                "relationships_changed": [{"entity": "张三", "change": "woke in town"}],
                "setting": "小镇",
                "tone": "quiet",
                "narrative_progression": "张三在小镇醒来。",
                "is_story_chapter": True,
            }
        },
        validation_warnings={
            13: ["Summary claims chapter number is 13, but source text explicitly states it is Chapter 1."]
        },
        fenced_validation_json=True,
    )

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )

    assert result["status"] == "success"
    assert result["chapters_processed"] == 1
    assert any(
        "source_heading_chapter_mismatch: expected=13, detected=1" in warning
        for warning in result["chapter_artifacts"][0]["warnings"]
    )
    assert llm.validation_prompts
    validation_prompt = llm.validation_prompts[0]
    assert "## CHAPTER IDENTITY CONTEXT" in validation_prompt
    assert "source_heading_chapter_mismatch: expected=13, detected=1" in validation_prompt

    paths = derive_paths(load_config(), release_id=release_id)
    zh_artifact = paths.summaries_dir / "chapter-13-zh.json"
    payload = json.loads(zh_artifact.read_text(encoding="utf-8"))
    assert payload["llm_validation_flags"] == []
    assert payload["llm_validation_warnings"] == [
        "Summary claims chapter number is 13, but source text explicitly states it is Chapter 1."
    ]

    conn = ensure_tracking_db(release_id)
    try:
        events = load_events(conn, run_id="summaries-001", release_id=release_id, limit=100)
    finally:
        conn.close()
    assert not [
        event
        for event in events
        if event.event_type == "preprocess-summaries.llm_validation_warning"
    ]


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
    assert result["chapters_processed"] == 1
    assert any(
        "summary_chapter_number_mismatch" in warning
        for warning in result["chapter_artifacts"][0]["warnings"]
    )


def test_summary_prompt_declares_pipeline_chapter_number_authoritative() -> None:
    prompt_path = Path("src/resemantica/llm/prompts/summary_zh_structured.txt")
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "canonical pipeline chapter number" in prompt


def test_summary_validation_prompt_declares_identity_context() -> None:
    prompt_path = Path("src/resemantica/llm/prompts/summary_zh_validate.txt")
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "CHAPTER IDENTITY CONTEXT" in prompt
    assert "The pipeline chapter number is canonical" in prompt
    assert "visible source headings" in prompt


def test_summary_english_derivation_is_deferred_until_all_chinese_work(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m45-summary-model-order"
    for i in [1, 2]:
        _write_extracted_chapter(
            release_id=release_id,
            chapter_number=i,
            source_text=f"第{i}章内容。",
            chapter_source_hash=f"hash-ch{i}",
        )

    calls: list[str] = []

    class RecordingSummaryLLM(ScriptedSummaryLLM):
        def generate_text(self, *, model_name: str, prompt: str) -> str:
            if "SUMMARY_ZH_STRUCTURED" in prompt:
                calls.append("zh_structured")
            elif "SUMMARY_ZH_VALIDATE" in prompt:
                calls.append("zh_validate")
            elif "SUMMARY_STORY_COMPACT" in prompt:
                calls.append("story_compact")
            elif "SUMMARY_EN_DERIVE" in prompt:
                calls.append("en_derive")
            return super().generate_text(model_name=model_name, prompt=prompt)

    llm = RecordingSummaryLLM(
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
        }
    )

    preprocess_summaries(release_id=release_id, run_id="summaries-001", llm_client=llm)

    assert calls == [
        "zh_structured",
        "zh_validate",
        "zh_structured",
        "zh_validate",
        "story_compact",
        "story_compact",
        "en_derive",
        "en_derive",
        "en_derive",
        "en_derive",
    ]


def test_concurrent_chinese_phase_keeps_ordered_story_and_compact_inputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m48-summary-concurrency"
    for chapter_number in [1, 2]:
        _write_extracted_chapter(
            release_id=release_id,
            chapter_number=chapter_number,
            source_text=f"第{chapter_number}章内容。",
            chapter_source_hash=f"hash-ch{chapter_number}",
        )

    chapter2_started = threading.Event()
    structured_completion_order: list[int] = []

    class OutOfOrderLLM(ScriptedSummaryLLM):
        def generate_text(self, *, model_name: str, prompt: str) -> str:
            if "SUMMARY_ZH_STRUCTURED" in prompt:
                chapter_match = re.search(r"## CHAPTER NUMBER\s+(\d+)", prompt)
                assert chapter_match is not None
                chapter_number = int(chapter_match.group(1))
                if chapter_number == 1:
                    chapter2_started.wait(timeout=2)
                else:
                    chapter2_started.set()
                structured_completion_order.append(chapter_number)
            return super().generate_text(model_name=model_name, prompt=prompt)

    llm = OutOfOrderLLM(
        {
            1: {
                "chapter_number": 1,
                "characters_mentioned": ["甲"],
                "key_events": ["甲出场"],
                "new_terms": [],
                "relationships_changed": [],
                "setting": "山镇",
                "tone": "quiet",
                "narrative_progression": "进展1。",
                "is_story_chapter": True,
            },
            2: {
                "chapter_number": 2,
                "characters_mentioned": ["乙"],
                "key_events": ["乙出场"],
                "new_terms": [],
                "relationships_changed": [],
                "setting": "山路",
                "tone": "tense",
                "narrative_progression": "进展2。",
                "is_story_chapter": True,
            },
        }
    )
    cfg = load_config()
    cfg.summaries.chapter_concurrency = 2

    preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
        config=cfg,
    )

    assert structured_completion_order[:2] == [2, 1]
    conn = open_connection(derive_paths(load_config(), release_id=release_id).db_path)
    ensure_summary_schema(conn)
    try:
        story = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=2,
            summary_type="story_so_far_zh",
        )
        compact = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=2,
            summary_type="story_so_far_zh_compact",
        )
        story_en = next(
            row
            for row in list_derived_summaries(conn, release_id=release_id, chapter_number=2)
            if row.summary_type == "story_so_far_en"
        )
        assert story is not None
        assert story.content_zh == "第1章：进展1。\n第2章：进展2。"
        assert compact is not None
        assert compact.content_zh == "进展1。\n进展2。"
        assert story_en.content_en == "EN::进展1。\n进展2。"
        assert story_en.source_summary_id == compact.summary_id
    finally:
        conn.close()


def test_story_compaction_failure_fails_preprocess_summaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m48-compact-fails"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="第一章内容。",
        chapter_source_hash="hash-ch1",
    )

    class EmptyCompactLLM(ScriptedSummaryLLM):
        def generate_text(self, *, model_name: str, prompt: str) -> str:
            if "SUMMARY_STORY_COMPACT" in prompt:
                return ""
            return super().generate_text(model_name=model_name, prompt=prompt)

    llm = EmptyCompactLLM(
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
            }
        }
    )

    with pytest.raises(ValueError, match="story_so_far_zh_compact"):
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
            if "SUMMARY_STORY_COMPACT" in prompt:
                current_match = re.search(
                    r"## CURRENT CHAPTER SUMMARY ZH SHORT\s*(.*?)\s*## TOKEN BUDGET",
                    prompt,
                    re.S,
                )
                return "" if current_match is None else current_match.group(1).strip()
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

    conn = open_connection(derive_paths(load_config(), release_id=release_id).db_path)
    ensure_summary_schema(conn)
    row = conn.execute(
        "SELECT validation_status, is_story_chapter FROM summary_drafts "
        "WHERE release_id = ? AND chapter_number = 2 AND summary_type = 'chapter_summary_zh_structured'",
        (release_id,),
    ).fetchone()
    assert row is not None, "draft should exist for the non-story chapter"
    assert int(row["is_story_chapter"]) == 0
    assert row["validation_status"] == "non_story_chapter"
    conn.close()


def test_guardrail_overrides_non_story(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m4-guardrail"

    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="第1章内容。" + "叙述内容。" * 200,  # > 500 chars
        chapter_source_hash="hash-ch1",
    )

    class HallucinatingLLM:
        def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
            if "SUMMARY_ZH_STRUCTURED" in prompt:
                return json.dumps({
                    "chapter_number": 1,
                    "characters_mentioned": [],
                    "key_events": [],
                    "new_terms": [],
                    "relationships_changed": [],
                    "setting": "",
                    "tone": "",
                    "narrative_progression": "Non-story chapter",
                    "is_story_chapter": False,
                }, ensure_ascii=False)
            if "SUMMARY_EN_DERIVE" in prompt:
                return "EN::content"
            if "SUMMARY_STORY_COMPACT" in prompt:
                current_match = re.search(
                    r"## CURRENT CHAPTER SUMMARY ZH SHORT\s*(.*?)\s*## TOKEN BUDGET",
                    prompt,
                    re.S,
                )
                return "" if current_match is None else current_match.group(1).strip()
            if "SUMMARY_ZH_VALIDATE" in prompt:
                return json.dumps({"flags": [], "warnings": []}, ensure_ascii=False)
            raise RuntimeError("Unexpected prompt")

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=HallucinatingLLM(),
    )
    assert result["status"] == "failed"

    failed = [r for r in result["chapter_artifacts"] if r.get("status") == "failed"]
    assert len(failed) == 1
    assert failed[0]["chapter_number"] == 1
    assert failed[0]["reason"] == "schema_failed"

    conn = open_connection(derive_paths(load_config(), release_id=release_id).db_path)
    ensure_summary_schema(conn)
    row = conn.execute(
        "SELECT validation_status, is_story_chapter FROM summary_drafts "
        "WHERE release_id = ? AND chapter_number = 1 AND summary_type = 'chapter_summary_zh_structured'",
        (release_id,),
    ).fetchone()
    assert row is not None
    assert int(row["is_story_chapter"]) == 1, "guardrail should have overridden to story"
    assert row["validation_status"] == "failed"
    conn.close()


def test_set_chapter_story_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "test-flag"

    from resemantica.db.summary_repo import save_summary_draft, set_chapter_story_flag

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)

    save_summary_draft(
        conn,
        release_id=release_id,
        chapter_number=1,
        summary_type="chapter_summary_zh_structured",
        content={"test": True},
        chapter_source_hash="h",
        model_name="m",
        prompt_version="1",
        run_id="r",
        validation_status="approved",
        is_story_chapter=1,
    )

    result = set_chapter_story_flag(
        conn, release_id=release_id, chapter_number=1, is_story=False,
    )
    assert result.action == "updated_existing"
    row = conn.execute(
        "SELECT is_story_chapter, validation_status FROM summary_drafts "
        "WHERE release_id = ? AND chapter_number = 1",
        (release_id,),
    ).fetchone()
    assert int(row["is_story_chapter"]) == 0
    assert row["validation_status"] == "non_story_chapter"

    result = set_chapter_story_flag(
        conn, release_id=release_id, chapter_number=1, is_story=True,
    )
    assert result.action == "updated_existing"
    row = conn.execute(
        "SELECT is_story_chapter, validation_status FROM summary_drafts "
        "WHERE release_id = ? AND chapter_number = 1",
        (release_id,),
    ).fetchone()
    assert int(row["is_story_chapter"]) == 1
    assert row["validation_status"] == "pending"

    result = set_chapter_story_flag(
        conn, release_id=release_id, chapter_number=99, is_story=True,
    )
    assert result.action == "confirmed_default_story"
    row = conn.execute(
        "SELECT 1 FROM summary_drafts WHERE release_id = ? AND chapter_number = 99",
        (release_id,),
    ).fetchone()
    assert row is None

    result = set_chapter_story_flag(
        conn,
        release_id=release_id,
        chapter_number=2,
        is_story=False,
        chapter_source_hash="hash-ch2",
    )
    assert result.action == "created_non_story"
    row = conn.execute(
        "SELECT content_json, chapter_source_hash, is_story_chapter, validation_status "
        "FROM summary_drafts WHERE release_id = ? AND chapter_number = 2",
        (release_id,),
    ).fetchone()
    assert row is not None
    assert json.loads(row["content_json"])["is_story_chapter"] is False
    assert row["chapter_source_hash"] == "hash-ch2"
    assert int(row["is_story_chapter"]) == 0
    assert row["validation_status"] == "non_story_chapter"

    result = set_chapter_story_flag(
        conn, release_id=release_id, chapter_number=3, is_story=False,
    )
    assert result.action == "missing_chapter_source_hash"
    assert not result.success
    conn.close()


def test_preseeded_non_story_flag_skips_summary_generation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m4-preseed-non-story"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="甲在山镇出现。",
        chapter_source_hash="hash-ch1",
    )
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=2,
        source_text="版权所有。未经许可，不得转载。",
        chapter_source_hash="hash-ch2",
    )

    from resemantica.db.summary_repo import set_chapter_story_flag

    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        result = set_chapter_story_flag(
            conn,
            release_id=release_id,
            chapter_number=2,
            is_story=False,
            chapter_source_hash="hash-ch2",
        )
        assert result.action == "created_non_story"
    finally:
        conn.close()

    structured_calls: list[int] = []

    class RecordingSummaryLLM(ScriptedSummaryLLM):
        def generate_text(self, *, model_name: str, prompt: str) -> str:
            if "SUMMARY_ZH_STRUCTURED" in prompt:
                chapter_match = re.search(r"## CHAPTER NUMBER\s+(\d+)", prompt)
                if chapter_match is None:
                    raise RuntimeError("chapter number missing from prompt")
                structured_calls.append(int(chapter_match.group(1)))
            return super().generate_text(model_name=model_name, prompt=prompt)

    llm = RecordingSummaryLLM(
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
            }
        }
    )

    result = preprocess_summaries(
        release_id=release_id,
        run_id="summaries-001",
        llm_client=llm,
    )

    assert result["status"] == "success"
    assert result["chapters_processed"] == 1
    assert structured_calls == [1]
    skipped = [r for r in result["chapter_artifacts"] if r.get("status") == "skipped"]
    assert len(skipped) == 1
    assert skipped[0]["chapter_number"] == 2
    assert skipped[0]["reason"] == "non_story_chapter"


def test_summary_checkpoint_read_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = load_config()
    paths = derive_paths(config, release_id="cp-test")
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        assert get_summary_checkpoint(conn, release_id="cp-test", run_id="r1") is None

        set_summary_checkpoint(conn, release_id="cp-test", run_id="r1", zh_last_chapter=5)
        cp = get_summary_checkpoint(conn, release_id="cp-test", run_id="r1")
        assert cp is not None
        assert cp[0] == 5
        assert cp[1] == 0
        assert cp[2] == 0

        set_summary_checkpoint(conn, release_id="cp-test", run_id="r1", story_last_chapter=4)
        cp = get_summary_checkpoint(conn, release_id="cp-test", run_id="r1")
        assert cp[0] == 5
        assert cp[1] == 4
        assert cp[2] == 0

        set_summary_checkpoint(conn, release_id="cp-test", run_id="r1", en_last_chapter=3)
        cp = get_summary_checkpoint(conn, release_id="cp-test", run_id="r1")
        assert cp[0] == 5
        assert cp[1] == 4
        assert cp[2] == 3

        set_summary_checkpoint(conn, release_id="cp-test", run_id="r1", zh_last_chapter=10, en_last_chapter=8)
        cp = get_summary_checkpoint(conn, release_id="cp-test", run_id="r1")
        assert cp[0] == 10
        assert cp[1] == 4
        assert cp[2] == 8

        set_summary_checkpoint(conn, release_id="cp-test", run_id="r2", zh_last_chapter=1)
        cp = get_summary_checkpoint(conn, release_id="cp-test", run_id="r1")
        assert cp[0] == 10
        assert cp[1] == 4
        assert cp[2] == 8
    finally:
        conn.close()


def test_preprocess_summaries_resume_skips_completed_zh_phase(tmp_path: Path, monkeypatch) -> None:
    """Verify checkpoint is written after a successful run, then resume skips completed chapters."""
    monkeypatch.chdir(tmp_path)
    release_id = "m-resume"
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

    llm = ScriptedSummaryLLM({
        1: {
            "chapter_number": 1,
            "characters_mentioned": ["张三"],
            "key_events": ["张三来到青云山"],
            "new_terms": ["青云山"],
            "relationships_changed": [],
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
            "relationships_changed": [],
            "setting": "青云山",
            "tone": "tense",
            "narrative_progression": "张三完成第一次试炼。",
            "is_story_chapter": True,
        },
    })

    result = preprocess_summaries(
        release_id=release_id,
        run_id="resume-001",
        llm_client=llm,
    )
    assert result["status"] == "success"
    assert result["chapters_processed"] == 2

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        cp = get_summary_checkpoint(conn, release_id=release_id, run_id="resume-001")
        assert cp is not None
        assert cp[0] == 2
    finally:
        conn.close()
