from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from loguru import logger

from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections


def translate_pass2(
    *,
    client: LLMClient,
    model_name: str,
    prompt_template: str,
    source_text: str,
    draft_text: str,
    full_source_block: str,
    prior_segment_translations: list[str] | None = None,
    glossary: str = "",
    alias_resolutions: str = "",
    matched_idioms: str = "",
    local_relationships: str = "",
    continuity_notes: str = "",
    retrieval_evidence: str = "",
    chapter_number: int | None = None,
    block_id: str | None = None,
    segment_id: str | None = None,
    fallback_callback: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    prior_segments = "\n".join(prior_segment_translations or [])
    prompt = render_named_sections(
        prompt_template,
        sections={
            "GLOSSARY": glossary,
            "SOURCE_TEXT": source_text,
            "DRAFT_TEXT": draft_text,
            "FULL_SOURCE_BLOCK": full_source_block,
            "PRIOR_SEGMENTS": prior_segments,
            "ALIAS_RESOLUTIONS": alias_resolutions,
            "MATCHED_IDIOMS": matched_idioms,
            "LOCAL_RELATIONSHIPS": local_relationships,
            "CONTINUITY_NOTES": continuity_notes,
            "RETRIEVAL_EVIDENCE": retrieval_evidence,
        },
    )
    response = client.generate_text(model_name=model_name, prompt=prompt)

    try:
        result: dict[str, Any] = json.loads(response)
    except json.JSONDecodeError:
        payload = {
            "reason": "json_parse_failed",
            "model_name": model_name,
            "chapter_number": chapter_number,
            "block_id": block_id,
            "segment_id": segment_id,
        }
        logger.warning(
            "Pass 2 JSON parse failed; falling back to original draft "
            "(model={}, chapter={}, block={}, segment={})",
            model_name,
            chapter_number,
            block_id,
            segment_id,
        )
        if fallback_callback is not None:
            fallback_callback(payload)
        return draft_text

    fidelity_errors_found = result.get("fidelity_errors_found", False)
    if not fidelity_errors_found:
        return draft_text

    corrected_text = result.get("corrected_text", "")
    if not corrected_text:
        payload = {
            "reason": "empty_corrected_text",
            "model_name": model_name,
            "chapter_number": chapter_number,
            "block_id": block_id,
            "segment_id": segment_id,
        }
        logger.warning(
            "Pass 2 fidelity errors found but corrected_text is empty; falling back to original draft "
            "(model={}, chapter={}, block={}, segment={})",
            model_name,
            chapter_number,
            block_id,
            segment_id,
        )
        if fallback_callback is not None:
            fallback_callback(payload)
        return draft_text

    return str(corrected_text)
