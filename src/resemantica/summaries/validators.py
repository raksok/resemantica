from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.llm.budget import ensure_prompt_within_budget
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections
from resemantica.settings import AppConfig
from resemantica.summaries._context import _format_glossary_context
from resemantica.validators import ValidationResult

_REQUIRED_FIELDS = {
    "chapter_number",
    "characters_mentioned",
    "key_events",
    "new_terms",
    "relationships_changed",
    "setting",
    "tone",
    "narrative_progression",
    "is_story_chapter",
}
_FUTURE_CHAPTER_ZH_RE = re.compile(r"第\s*(\d+)\s*章")
_FUTURE_CHAPTER_EN_RE = re.compile(r"\bchapter\s+(\d+)\b", re.IGNORECASE)


def _is_list_of_strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _collect_text_fields(summary: dict[str, object]) -> list[str]:
    texts: list[str] = []
    for value in summary.values():
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    texts.append(item)
                elif isinstance(item, dict):
                    for nested in item.values():
                        if isinstance(nested, str):
                            texts.append(nested)
    return texts


def _validate_schema(
    summary: dict[str, object],
    expected_chapter_number: int,
) -> list[str]:
    errors: list[str] = []
    missing = sorted(_REQUIRED_FIELDS - set(summary.keys()))
    if missing:
        errors.append(f"schema_invalid: missing fields: {', '.join(missing)}")
        return errors

    chapter_number = summary.get("chapter_number")
    if not isinstance(chapter_number, int):
        errors.append("schema_invalid: chapter_number must be an integer")
    elif chapter_number != expected_chapter_number:
        errors.append(
            "continuity_conflict: chapter_number does not match extracted chapter number"
        )

    if not _is_list_of_strings(summary.get("characters_mentioned")):
        errors.append("schema_invalid: characters_mentioned must be a list of strings")
    if not _is_list_of_strings(summary.get("key_events")):
        errors.append("schema_invalid: key_events must be a list of strings")
    if not _is_list_of_strings(summary.get("new_terms")):
        errors.append("schema_invalid: new_terms must be a list of strings")

    relationships = summary.get("relationships_changed")
    if not isinstance(relationships, list):
        errors.append("schema_invalid: relationships_changed must be a list")
    else:
        for index, item in enumerate(relationships):
            if not isinstance(item, dict):
                errors.append(
                    f"schema_invalid: relationships_changed[{index}] must be an object"
                )
                continue
            entity = item.get("entity")
            change = item.get("change")
            if not isinstance(entity, str) or not entity.strip():
                errors.append(
                    f"schema_invalid: relationships_changed[{index}].entity must be a non-empty string"
                )
            if not isinstance(change, str) or not change.strip():
                errors.append(
                    f"schema_invalid: relationships_changed[{index}].change must be a non-empty string"
                )

    setting = summary.get("setting")
    if not isinstance(setting, str) or not setting.strip():
        errors.append("schema_invalid: setting must be a non-empty string")

    tone = summary.get("tone")
    if not isinstance(tone, str) or not tone.strip():
        errors.append("schema_invalid: tone must be a non-empty string")

    narrative_progression = summary.get("narrative_progression")
    if not isinstance(narrative_progression, str) or not narrative_progression.strip():
        errors.append("schema_invalid: narrative_progression must be a non-empty string")

    is_story_chapter = summary.get("is_story_chapter")
    if not isinstance(is_story_chapter, bool):
        errors.append("schema_invalid: is_story_chapter must be a boolean")

    return errors


def _validate_future_knowledge(
    summary: dict[str, object],
    *,
    chapter_number: int,
) -> list[str]:
    errors: list[str] = []
    for text in _collect_text_fields(summary):
        for match in _FUTURE_CHAPTER_ZH_RE.finditer(text):
            referenced = int(match.group(1))
            if referenced > chapter_number:
                errors.append(
                    f"future_knowledge: references chapter {referenced} while validating chapter {chapter_number}"
                )
        for match in _FUTURE_CHAPTER_EN_RE.finditer(text):
            referenced = int(match.group(1))
            if referenced > chapter_number:
                errors.append(
                    f"future_knowledge: references chapter {referenced} while validating chapter {chapter_number}"
                )
    return errors


def validate_chinese_summary(
    *,
    structured_summary: dict[str, Any],
    expected_chapter_number: int,
) -> ValidationResult:
    errors: list[str] = []
    errors.extend(_validate_schema(structured_summary, expected_chapter_number))
    errors.extend(
        _validate_future_knowledge(
            structured_summary,
            chapter_number=expected_chapter_number,
        )
    )

    is_story_chapter = structured_summary.get("is_story_chapter")
    if is_story_chapter is False:
        errors.insert(0, "non_story_chapter_flagged")

    return ValidationResult(
        status="failed" if errors else "success",
        errors=errors,
        warnings=[],
    )


def validate_chinese_summary_content(
    *,
    llm_client: LLMClient,
    model_name: str,
    prompt_template: str,
    source_text_zh: str,
    structured_summary: dict[str, object],
    locked_glossary: list[LockedGlossaryEntry],
    config: AppConfig | None = None,
) -> list[str]:
    prompt = render_named_sections(
        prompt_template,
        sections={
            "CHAPTER_NUMBER": str(structured_summary.get("chapter_number", "")),
            "SOURCE_TEXT": source_text_zh,
            "STRUCTURED_SUMMARY": json.dumps(structured_summary, ensure_ascii=False, indent=2),
            "LOCKED_GLOSSARY": _format_glossary_context(locked_glossary),
        },
    )
    if config is not None:
        chapter_number = structured_summary.get("chapter_number")
        analyst_budget = config.models.effective_max_context_per_pass(
            "analyst", config.budget.max_context_per_pass, config.llm.context_window
        )
        ensure_prompt_within_budget(
            prompt,
            config=config,
            stage_name="preprocess-summaries.validation",
            chapter_number=chapter_number if isinstance(chapter_number, int) else None,
            max_tokens=analyst_budget,
        )
    raw = llm_client.generate_text(model_name=model_name, prompt=prompt).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Summary validation JSON parse error: raw={}", raw[:200])
        return ["<parse_error>"]
    flags = parsed.get("flags", []) if isinstance(parsed, dict) else []
    if not isinstance(flags, list):
        return []
    return [str(f) for f in flags]
