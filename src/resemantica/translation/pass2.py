from __future__ import annotations

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
    return client.generate_text(model_name=model_name, prompt=prompt)

