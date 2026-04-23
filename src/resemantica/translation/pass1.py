from __future__ import annotations

from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections


def translate_pass1(
    *,
    client: LLMClient,
    model_name: str,
    prompt_template: str,
    source_text: str,
) -> str:
    prompt = render_named_sections(
        prompt_template,
        sections={
            "SOURCE_TEXT": source_text,
        },
    )
    return client.generate_text(model_name=model_name, prompt=prompt)

