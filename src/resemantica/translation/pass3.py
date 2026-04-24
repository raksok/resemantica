from __future__ import annotations

from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections


def translate_pass3(
    *,
    client: LLMClient,
    model_name: str,
    prompt_template: str,
    source_text: str,
    pass2_output: str,
    glossary_text: str,
) -> str:
    prompt = render_named_sections(
        prompt_template,
        sections={
            "SOURCE_TEXT": source_text,
            "PASS2_OUTPUT": pass2_output,
            "GLOSSARY": glossary_text,
        },
    )
    return client.generate_text(model_name=model_name, prompt=prompt)
