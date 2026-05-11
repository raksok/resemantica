from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from resemantica.db.summary_repo import (
    SummaryDraftRecord,
    ValidatedSummaryZhRecord,
    save_chapter_structured_and_short,
    save_summary_draft,
    set_summary_draft_status,
)
from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.llm.budget import (
    PromptBudgetError,
    chunk_text_for_prompt,
    ensure_prompt_within_budget,
)
from resemantica.llm.cache import LLMCacheIdentity, hash_prompt, load_cached_text, save_cached_text
from resemantica.llm.client import LLMClient, record_cache_hit
from resemantica.llm.prompts import render_named_sections
from resemantica.llm.tokens import count_tokens
from resemantica.settings import AppConfig, load_config
from resemantica.summaries._context import _format_glossary_context
from resemantica.summaries.validators import validate_chinese_summary
from resemantica.validators import ValidationResult

_NON_STORY_GUARDRAIL_LENGTH = 500
_SOURCE_PATH_CHAPTER_RE = re.compile(r"(?:chapter|chap|ch)[-_ ]*0*(\d+)", re.IGNORECASE)
_SOURCE_HEADING_ZH_RE = re.compile(r"第\s*([0-9零〇一二两三四五六七八九十百千]+)\s*[章节回]")
_SOURCE_HEADING_EN_RE = re.compile(r"\bchapter\s+0*(\d+)\b", re.IGNORECASE)
_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000}


@dataclass(slots=True)
class GeneratedChapterSummary:
    structured_summary: dict[str, object]
    draft_record: SummaryDraftRecord
    structured_record: ValidatedSummaryZhRecord
    short_record: ValidatedSummaryZhRecord
    validation: ValidationResult
    warnings: list[str]


def _parse_chapter_number_token(value: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.isdigit():
        return int(stripped)
    total = 0
    current = 0
    seen = False
    for char in stripped:
        if char in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[char]
            seen = True
            continue
        unit = _CHINESE_UNITS.get(char)
        if unit is None:
            return None
        total += (current or 1) * unit
        current = 0
        seen = True
    if not seen:
        return None
    return total + current


def _detect_path_chapter_number(source_document_path: str) -> int | None:
    match = _SOURCE_PATH_CHAPTER_RE.search(Path(source_document_path).name)
    if match is None:
        return None
    return int(match.group(1))


def _detect_source_heading_chapter_number(source_text_zh: str) -> int | None:
    candidate = source_text_zh[:500]
    zh_match = _SOURCE_HEADING_ZH_RE.search(candidate)
    if zh_match is not None:
        return _parse_chapter_number_token(zh_match.group(1))
    en_match = _SOURCE_HEADING_EN_RE.search(candidate)
    if en_match is not None:
        return int(en_match.group(1))
    return None


def _normalize_summary_chapter_identity(
    *,
    parsed: dict[str, Any],
    canonical_chapter_number: int,
    source_document_path: str,
    source_text_zh: str,
) -> tuple[list[str], set[int]]:
    warnings: list[str] = []
    reported = parsed.get("chapter_number")
    if isinstance(reported, int) and reported != canonical_chapter_number:
        parsed["chapter_number"] = canonical_chapter_number
        warnings.append(
            "summary_chapter_number_mismatch:"
            f" expected={canonical_chapter_number}, reported={reported}"
        )

    path_chapter = _detect_path_chapter_number(source_document_path)
    if path_chapter is not None and path_chapter != canonical_chapter_number:
        warnings.append(
            "source_filename_chapter_mismatch:"
            f" expected={canonical_chapter_number}, source_document_path={source_document_path},"
            f" detected={path_chapter}"
        )

    heading_chapter = _detect_source_heading_chapter_number(source_text_zh)
    allowed_future_numbers: set[int] = set()
    if heading_chapter is not None:
        allowed_future_numbers.add(heading_chapter)
        if heading_chapter != canonical_chapter_number:
            warnings.append(
                "source_heading_chapter_mismatch:"
                f" expected={canonical_chapter_number}, detected={heading_chapter}"
            )
    return warnings, allowed_future_numbers


def _parse_summary(raw_output: str) -> dict[str, Any] | None:
    text = raw_output.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        else:
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _dedupe_strings(values: list[object]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _list_field(row: dict[str, Any], field_name: str) -> list[object]:
    value = row.get(field_name, [])
    return value if isinstance(value, list) else []


def _combine_chunk_summaries(
    *,
    chapter_number: int,
    summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    story_values = [row.get("is_story_chapter", True) for row in summaries]
    relationships: list[dict[str, object]] = []
    for row in summaries:
        for item in row.get("relationships_changed", []):
            if isinstance(item, dict):
                relationships.append(item)
    narrative = "\n".join(
        str(row.get("narrative_progression", "")).strip()
        for row in summaries
        if str(row.get("narrative_progression", "")).strip()
    )
    return {
        "chapter_number": chapter_number,
        "characters_mentioned": _dedupe_strings(
            [item for row in summaries for item in _list_field(row, "characters_mentioned")]
        ),
        "key_events": _dedupe_strings([item for row in summaries for item in _list_field(row, "key_events")]),
        "new_terms": _dedupe_strings([item for row in summaries for item in _list_field(row, "new_terms")]),
        "relationships_changed": relationships,
        "setting": str(next((row.get("setting") for row in summaries if row.get("setting")), "")),
        "tone": str(next((row.get("tone") for row in summaries if row.get("tone")), "")),
        "narrative_progression": narrative,
        "is_story_chapter": any(value is not False for value in story_values),
    }


def _generate_structured_summary(
    *,
    release_id: str,
    chapter_number: int,
    chapter_source_hash: str,
    source_text_zh: str,
    locked_glossary: list[LockedGlossaryEntry],
    llm_client: LLMClient,
    model_name: str,
    prompt_template: str,
    prompt_version: str,
    config: AppConfig,
    cache_root: Path | None,
) -> tuple[dict[str, Any] | None, str]:
    static_prompt = render_named_sections(
        prompt_template,
        sections={
            "CHAPTER_NUMBER": str(chapter_number),
            "SOURCE_TEXT": "",
            "LOCKED_GLOSSARY": _format_glossary_context(locked_glossary),
        },
    )

    analyst_budget = config.models.effective_max_context_per_pass(
        "analyst", config.budget.max_context_per_pass, config.llm.context_window
    )
    chunks = chunk_text_for_prompt(
        source_text_zh,
        config=config,
        static_prompt_tokens=count_tokens(static_prompt),
        max_tokens=analyst_budget,
    )
    parsed_chunks: list[dict[str, Any]] = []
    raw_outputs: list[str] = []
    for chunk in chunks:
        chunk_text = (
            source_text_zh
            if chunk.chunk_count == 1
            else f"[Chunk {chunk.chunk_index}/{chunk.chunk_count}]\n{chunk.text}"
        )
        prompt = render_named_sections(
            prompt_template,
            sections={
                "CHAPTER_NUMBER": str(chapter_number),
                "SOURCE_TEXT": chunk_text,
                "LOCKED_GLOSSARY": _format_glossary_context(locked_glossary),
            },
        )
        ensure_prompt_within_budget(
            prompt,
            config=config,
            stage_name="preprocess-summaries.structured",
            chapter_number=chapter_number,
            max_tokens=analyst_budget,
        )
        identity = LLMCacheIdentity(
            release_id=release_id,
            chapter_number=chapter_number,
            source_hash=chapter_source_hash,
            stage_name="preprocess-summaries.structured",
            chunk_index=chunk.chunk_index,
            model_name=model_name,
            prompt_version=prompt_version,
            prompt_hash=hash_prompt(prompt),
        )
        cached = load_cached_text(cache_root, identity) if cache_root is not None else None
        if cached is not None:
            record_cache_hit(llm_client)
        raw_output = (
            cached
            if cached is not None
            else llm_client.generate_text(model_name=model_name, prompt=prompt).strip()
        )
        if cache_root is not None and cached is None:
            save_cached_text(cache_root, identity, raw_output)
        raw_outputs.append(raw_output)
        parsed = _parse_summary(raw_output)
        if parsed is None and cached is not None:
            assert cache_root is not None
            raw_output = llm_client.generate_text(model_name=model_name, prompt=prompt).strip()
            save_cached_text(cache_root, identity, raw_output)
            raw_outputs[-1] = raw_output
            parsed = _parse_summary(raw_output)
        if parsed is None:
            return None, raw_output
        parsed_chunks.append(parsed)

    if len(parsed_chunks) == 1:
        return parsed_chunks[0], raw_outputs[0]
    return _combine_chunk_summaries(chapter_number=chapter_number, summaries=parsed_chunks), "\n".join(raw_outputs)


def generate_chapter_summary(
    *,
    conn: sqlite3.Connection,
    release_id: str,
    run_id: str,
    chapter_number: int,
    chapter_source_hash: str,
    source_document_path: str,
    source_text_zh: str,
    locked_glossary: list[LockedGlossaryEntry],
    llm_client: LLMClient,
    model_name: str,
    prompt_template: str,
    prompt_version: str,
    config: AppConfig | None = None,
    cache_root: Path | None = None,
) -> GeneratedChapterSummary | None:
    config_obj = config or load_config()
    try:
        parsed, raw_output = _generate_structured_summary(
            release_id=release_id,
            chapter_number=chapter_number,
            chapter_source_hash=chapter_source_hash,
            source_text_zh=source_text_zh,
            locked_glossary=locked_glossary,
            llm_client=llm_client,
            model_name=model_name,
            prompt_template=prompt_template,
            prompt_version=prompt_version,
            config=config_obj,
            cache_root=cache_root,
        )
    except PromptBudgetError as exc:
        is_story = 1
        save_summary_draft(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_structured",
            content={
                "raw_output": "",
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

    if parsed is None:
        is_story = 1
        save_summary_draft(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_structured",
            content={
                "raw_output": raw_output,
                "parse_error": "invalid JSON object",
            },
            chapter_source_hash=chapter_source_hash,
            model_name=model_name,
            prompt_version=prompt_version,
            run_id=run_id,
            validation_status="failed",
            is_story_chapter=is_story,
        )
        return None

    identity_warnings, allowed_future_chapter_numbers = _normalize_summary_chapter_identity(
        parsed=parsed,
        canonical_chapter_number=chapter_number,
        source_document_path=source_document_path,
        source_text_zh=source_text_zh,
    )

    is_story_chapter = parsed.get("is_story_chapter", True)

    if is_story_chapter is False and len(source_text_zh) > _NON_STORY_GUARDRAIL_LENGTH:
        logger.warning(
            "Guardrail: overrode non-story flag for chapter {} "
            "(source_text_zh length={}, threshold={})",
            chapter_number,
            len(source_text_zh),
            _NON_STORY_GUARDRAIL_LENGTH,
        )
        is_story_chapter = True

    is_story = 0 if is_story_chapter is False else 1

    if is_story == 0:
        save_summary_draft(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_structured",
            content=parsed,
            chapter_source_hash=chapter_source_hash,
            model_name=model_name,
            prompt_version=prompt_version,
            run_id=run_id,
            validation_status="non_story_chapter",
            is_story_chapter=0,
        )
        return None

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
        is_story_chapter=1,
    )

    validation = validate_chinese_summary(
        structured_summary=parsed,
        expected_chapter_number=chapter_number,
        allowed_future_chapter_numbers=allowed_future_chapter_numbers,
    )
    if not validation.is_valid:
        save_summary_draft(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_structured",
            content={
                "parsed_summary": parsed,
                "validation_errors": validation.errors,
                "warnings": identity_warnings,
            },
            chapter_source_hash=chapter_source_hash,
            model_name=model_name,
            prompt_version=prompt_version,
            run_id=run_id,
            validation_status="failed",
            is_story_chapter=1,
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
        warnings=identity_warnings,
    )
