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
_SUMMARY_UNKNOWN_VALUE_ZH = "未明确"
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
_MAX_GENERATION_ATTEMPTS = 4
_MAX_RETRY_ERRORS = 4


@dataclass(slots=True)
class GeneratedChapterSummary:
    structured_summary: dict[str, object]
    draft_record: SummaryDraftRecord
    structured_record: ValidatedSummaryZhRecord
    short_record: ValidatedSummaryZhRecord
    validation: ValidationResult
    warnings: list[str]
    identity_warnings: list[str]


@dataclass(slots=True)
class _SummaryAttemptFailure:
    attempt_number: int
    category: str
    errors: list[str]
    hints: list[str]
    raw_output: str = ""
    parsed_summary: dict[str, Any] | None = None
    warnings: list[str] | None = None


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


def _categorize_validation_errors(errors: list[str]) -> str:
    if any("future_knowledge" in error for error in errors):
        return "future_knowledge_failed"
    if any("continuity_conflict" in error for error in errors):
        return "chapter_identity_failed"
    if any("schema_invalid" in error for error in errors):
        return "schema_failed"
    return "validation_failed"


def _missing_schema_fields(error: str) -> set[str]:
    prefix = "schema_invalid: missing fields:"
    if not error.startswith(prefix):
        return set()
    return {field.strip() for field in error.removeprefix(prefix).split(",") if field.strip()}


def _classify_recoverable_schema_errors(errors: list[str]) -> tuple[set[str], list[str]]:
    recoverable: set[str] = set()
    unrecoverable: list[str] = []
    for error in errors:
        missing_fields = _missing_schema_fields(error)
        if missing_fields:
            if missing_fields == {"is_story_chapter"}:
                recoverable.add("missing_is_story_chapter")
            else:
                unrecoverable.append(error)
            continue
        if error.startswith("schema_invalid: relationships_changed["):
            recoverable.add("invalid_relationships_changed_entries")
            continue
        if error in {
            "schema_invalid: setting must be a non-empty string",
            "schema_invalid: tone must be a non-empty string",
        }:
            recoverable.add("empty_setting_or_tone")
            continue
        unrecoverable.append(error)
    return recoverable, unrecoverable


def _valid_relationship_change(item: object) -> dict[str, object] | None:
    if not isinstance(item, dict):
        return None
    entity = item.get("entity")
    change = item.get("change")
    if not isinstance(entity, str) or not entity.strip():
        return None
    if not isinstance(change, str) or not change.strip():
        return None
    return {"entity": entity.strip(), "change": change.strip()}


def _recover_summary_schema(
    parsed: dict[str, Any],
    *,
    errors: list[str],
) -> list[str] | None:
    recoverable_classes, unrecoverable_errors = _classify_recoverable_schema_errors(errors)
    if not recoverable_classes or unrecoverable_errors:
        return None

    warnings: list[str] = []
    if "missing_is_story_chapter" in recoverable_classes:
        parsed["is_story_chapter"] = True
        warnings.append("missing_is_story_chapter_defaulted_true")

    if "invalid_relationships_changed_entries" in recoverable_classes:
        relationships = parsed.get("relationships_changed")
        if not isinstance(relationships, list):
            return None
        parsed["relationships_changed"] = [
            item
            for item in (_valid_relationship_change(item) for item in relationships)
            if item is not None
        ]
        warnings.append("invalid_relationships_changed_entries_dropped")

    if "empty_setting_or_tone" in recoverable_classes:
        for field_name in ("setting", "tone"):
            value = parsed.get(field_name)
            if not isinstance(value, str) or not value.strip():
                parsed[field_name] = _SUMMARY_UNKNOWN_VALUE_ZH
        warnings.append("empty_setting_or_tone_defaulted")

    return warnings


def _correction_hints(category: str, errors: list[str] | None = None) -> list[str]:
    if category == "parse_failed":
        return ["Return one valid JSON object only.", "Do not include markdown fences or prose."]
    if category == "schema_failed":
        field_hints: list[str] = []
        for error in errors or []:
            missing_fields = _missing_schema_fields(error)
            if "is_story_chapter" in missing_fields:
                field_hints.append('Add "is_story_chapter" as literal true or false.')
            if error.startswith("schema_invalid: relationships_changed["):
                field_hints.append(
                    'Use only relationships_changed objects: {"entity":"...","change":"..."}.'
                )
            if error == "schema_invalid: relationships_changed must be a list":
                field_hints.append('"relationships_changed" must be an array, not a string.')
            if error == "schema_invalid: setting must be a non-empty string":
                field_hints.append('"setting" must be a short non-empty string.')
            if error == "schema_invalid: tone must be a non-empty string":
                field_hints.append('"tone" must be a short non-empty string.')
            if error == "schema_invalid: narrative_progression must be a non-empty string":
                field_hints.append('"narrative_progression" must be a non-empty Chinese sentence.')
        if field_hints:
            return list(dict.fromkeys(field_hints))
        return ["Use every required field with the exact expected type."]
    if category == "future_knowledge_failed":
        return ["Use only facts visible in the current source text.", "Do not mention later chapters."]
    if category == "chapter_identity_failed":
        return ["Echo the canonical pipeline chapter number exactly."]
    return ["Correct only the listed validation issues."]


def _render_retry_feedback(failure: _SummaryAttemptFailure | None) -> str:
    if failure is None:
        return ""
    errors = failure.errors[:_MAX_RETRY_ERRORS]
    lines = [
        "## RETRY FEEDBACK",
        f"Previous attempt: {failure.attempt_number}",
        f"Failure category: {failure.category}",
    ]
    if errors:
        lines.append("Validation errors:")
        lines.extend(f"- {error}" for error in errors)
    if failure.hints:
        lines.append("Correction hints:")
        lines.extend(f"- {hint}" for hint in failure.hints)
    lines.append("Do not copy any previous invalid output. Produce a fresh compact JSON object.")
    return "\n".join(lines)


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
    retry_feedback: _SummaryAttemptFailure | None = None,
) -> tuple[dict[str, Any] | None, str]:
    retry_feedback_text = _render_retry_feedback(retry_feedback)
    static_prompt = render_named_sections(
        prompt_template,
        sections={
            "CHAPTER_NUMBER": str(chapter_number),
            "SOURCE_TEXT": "",
            "LOCKED_GLOSSARY": _format_glossary_context(locked_glossary),
            "RETRY_FEEDBACK": retry_feedback_text,
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
                "RETRY_FEEDBACK": retry_feedback_text,
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


def _save_final_failed_draft(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    chapter_source_hash: str,
    model_name: str,
    prompt_version: str,
    failure: _SummaryAttemptFailure,
) -> SummaryDraftRecord:
    content: dict[str, object] = {
        "attempts": failure.attempt_number,
        "failure_category": failure.category,
        "validation_errors": failure.errors,
        "correction_hints": failure.hints,
    }
    if failure.parsed_summary is not None:
        content["parsed_summary"] = failure.parsed_summary
    else:
        content["raw_output"] = failure.raw_output
    if failure.warnings:
        content["warnings"] = failure.warnings
    return save_summary_draft(
        conn,
        release_id=release_id,
        chapter_number=chapter_number,
        summary_type="chapter_summary_zh_structured",
        content=content,
        chapter_source_hash=chapter_source_hash,
        model_name=model_name,
        prompt_version=prompt_version,
        run_id=run_id,
        validation_status="failed",
        is_story_chapter=1,
    )


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

    _existing = conn.execute(
        """
        SELECT is_story_chapter
        FROM summary_drafts
        WHERE release_id = ?
          AND chapter_number = ?
          AND summary_type = 'chapter_summary_zh_structured'
        LIMIT 1
        """,
        (release_id, chapter_number),
    ).fetchone()
    if _existing is not None and int(_existing["is_story_chapter"]) == 0:
        logger.info(
            "Chapter {}: respecting existing non-story flag, skipping LLM",
            chapter_number,
        )
        return None

    failure: _SummaryAttemptFailure | None = None
    parsed: dict[str, Any] | None = None
    validation: ValidationResult | None = None
    identity_warnings: list[str] = []
    recovery_warnings: list[str] = []
    recoverable_schema_retries: set[str] = set()
    allowed_future_chapter_numbers: set[int] = set()
    try:
        for attempt_number in range(1, _MAX_GENERATION_ATTEMPTS + 1):
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
                retry_feedback=failure,
            )
            if parsed is None:
                category = "parse_failed"
                failure = _SummaryAttemptFailure(
                    attempt_number=attempt_number,
                    category=category,
                    errors=["invalid JSON object"],
                    hints=_correction_hints(category),
                    raw_output=raw_output,
                )
                continue

            identity_warnings, allowed_future_chapter_numbers = _normalize_summary_chapter_identity(
                parsed=parsed,
                canonical_chapter_number=chapter_number,
                source_document_path=source_document_path,
                source_text_zh=source_text_zh,
            )

            is_story_chapter = parsed.get("is_story_chapter", True)
            guardrail_overrode_non_story = False

            if is_story_chapter is False and len(source_text_zh) > _NON_STORY_GUARDRAIL_LENGTH:
                logger.warning(
                    "Guardrail: overrode non-story flag for chapter {} "
                    "(source_text_zh length={}, threshold={})",
                    chapter_number,
                    len(source_text_zh),
                    _NON_STORY_GUARDRAIL_LENGTH,
                )
                is_story_chapter = True
                parsed["is_story_chapter"] = True
                guardrail_overrode_non_story = True

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

            validation = validate_chinese_summary(
                structured_summary=parsed,
                expected_chapter_number=chapter_number,
                allowed_future_chapter_numbers=allowed_future_chapter_numbers,
            )
            if validation.is_valid:
                break

            category = _categorize_validation_errors(validation.errors)
            recoverable_classes, unrecoverable_errors = _classify_recoverable_schema_errors(
                validation.errors
            )
            if (
                recoverable_classes
                and not unrecoverable_errors
                and not guardrail_overrode_non_story
            ):
                if not recoverable_classes.issubset(recoverable_schema_retries):
                    recoverable_schema_retries.update(recoverable_classes)
                else:
                    recovered_warnings = _recover_summary_schema(
                        parsed,
                        errors=validation.errors,
                    )
                    if recovered_warnings is not None:
                        validation = validate_chinese_summary(
                            structured_summary=parsed,
                            expected_chapter_number=chapter_number,
                            allowed_future_chapter_numbers=allowed_future_chapter_numbers,
                        )
                        if validation.is_valid:
                            recovery_warnings.extend(recovered_warnings)
                            logger.warning(
                                "Recovered summary schema for chapter {}: {}",
                                chapter_number,
                                recovered_warnings,
                            )
                            break
                        category = _categorize_validation_errors(validation.errors)
            failure = _SummaryAttemptFailure(
                attempt_number=attempt_number,
                category=category,
                errors=validation.errors,
                hints=_correction_hints(category, validation.errors),
                parsed_summary=parsed,
                warnings=identity_warnings + recovery_warnings,
            )
        else:
            assert failure is not None
            _save_final_failed_draft(
                conn,
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                chapter_source_hash=chapter_source_hash,
                model_name=model_name,
                prompt_version=prompt_version,
                failure=failure,
            )
            return None
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

    assert parsed is not None
    assert validation is not None
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
        warnings=identity_warnings + recovery_warnings,
        identity_warnings=identity_warnings,
    )
