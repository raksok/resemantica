from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from resemantica.db.summary_repo import (
    SummaryDraftRecord,
    ValidatedSummaryZhRecord,
    save_chapter_structured_and_short,
    save_summary_draft,
    set_summary_draft_status,
)
from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections
from resemantica.summaries.validators import (
    SummaryValidationResult,
    validate_chinese_summary,
)


def _glossary_context(entries: list[LockedGlossaryEntry]) -> str:
    if not entries:
        return "(empty)"
    return "\n".join(
        f"- {entry.source_term} => {entry.target_term} ({entry.category})"
        for entry in entries
    )


@dataclass(slots=True)
class GeneratedChapterSummary:
    structured_summary: dict[str, object]
    draft_record: SummaryDraftRecord
    structured_record: ValidatedSummaryZhRecord
    short_record: ValidatedSummaryZhRecord
    validation: SummaryValidationResult


def generate_chapter_summary(
    *,
    conn: sqlite3.Connection,
    release_id: str,
    run_id: str,
    chapter_number: int,
    chapter_source_hash: str,
    source_text_zh: str,
    locked_glossary: list[LockedGlossaryEntry],
    llm_client: LLMClient,
    model_name: str,
    prompt_template: str,
    prompt_version: str,
) -> GeneratedChapterSummary | None:
    prompt = render_named_sections(
        prompt_template,
        sections={
            "CHAPTER_NUMBER": str(chapter_number),
            "SOURCE_TEXT": source_text_zh,
            "LOCKED_GLOSSARY": _glossary_context(locked_glossary),
        },
    )
    raw_output = llm_client.generate_text(model_name=model_name, prompt=prompt).strip()

    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        is_story = 1
        save_summary_draft(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_structured",
            content={
                "raw_output": raw_output,
                "parse_error": str(exc),
            },
            chapter_source_hash=chapter_source_hash,
            model_name=model_name,
            prompt_version=prompt_version,
            run_id=run_id,
            validation_status="failed",
            is_story_chapter=is_story,
        )
        return None

    if not isinstance(parsed, dict):
        is_story = 1
        save_summary_draft(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_structured",
            content={
                "raw_output": raw_output,
                "parse_error": "root is not an object",
            },
            chapter_source_hash=chapter_source_hash,
            model_name=model_name,
            prompt_version=prompt_version,
            run_id=run_id,
            validation_status="failed",
            is_story_chapter=is_story,
        )
        return None

    is_story_chapter = parsed.get("is_story_chapter", True)
    is_story = 0 if is_story_chapter is False else 1

    draft_record = save_summary_draft(
        conn,
        release_id=release_id,
        chapter_number=chapter_number,
        summary_type="chapter_summary_zh_structured",
        content=parsed,
        chapter_source_hash=chapter_source_hash,
        model_name=model_name,
        prompt_version=prompt_version,
        run_id=run_id,
        validation_status="pending",
        is_story_chapter=is_story,
    )

    validation = validate_chinese_summary(
        structured_summary=parsed,
        expected_chapter_number=chapter_number,
        locked_glossary=locked_glossary,
    )
    if not validation.is_valid:
        set_summary_draft_status(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_structured",
            validation_status="failed",
        )
        return None

    if is_story == 0:
        set_summary_draft_status(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_structured",
            validation_status="non_story_chapter",
        )
        return None

    narrative_progression = str(parsed["narrative_progression"]).strip()
    structured_record, short_record = save_chapter_structured_and_short(
        conn,
        release_id=release_id,
        chapter_number=chapter_number,
        structured_summary=parsed,
        narrative_progression=narrative_progression,
        derived_from_chapter_hash=chapter_source_hash,
        run_id=run_id,
        validation_status="approved",
    )
    set_summary_draft_status(
        conn,
        release_id=release_id,
        chapter_number=chapter_number,
        summary_type="chapter_summary_zh_structured",
        validation_status="approved",
    )

    return GeneratedChapterSummary(
        structured_summary=parsed,
        draft_record=draft_record,
        structured_record=structured_record,
        short_record=short_record,
        validation=validation,
    )
