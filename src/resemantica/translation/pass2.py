from __future__ import annotations

import json
import logging
from typing import Any

from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections

logger = logging.getLogger(__name__)


def translate_pass2(
    *,
    client: LLMClient,
    model_name: str,
    prompt_template: str,
    source_text: str,
    draft_text: str,
    full_source_block: str,
    prior_segment_translations: list[str] | None = None,
) -> str:
    prior_segments = "\n".join(prior_segment_translations or [])
    prompt = render_named_sections(
        prompt_template,
        sections={
            "SOURCE_TEXT": source_text,
            "DRAFT_TEXT": draft_text,
            "FULL_SOURCE_BLOCK": full_source_block,
            "PRIOR_SEGMENTS": prior_segments,
        },
    )
    response = client.generate_text(model_name=model_name, prompt=prompt)

    try:
        result: dict[str, Any] = json.loads(response)
    except json.JSONDecodeError:
        logger.warning("Pass 2 JSON parse failed, falling back to original draft")
        return draft_text

    fidelity_errors_found = result.get("fidelity_errors_found", False)
    if not fidelity_errors_found:
        return draft_text

    corrected_text = result.get("corrected_text", "")
    if not corrected_text:
        logger.warning("Pass 2 fidelity errors found but corrected_text empty, falling back to original draft")
        return draft_text

    return str(corrected_text)
