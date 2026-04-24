from __future__ import annotations

from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections


def _strip_artifacts(output: str, source_text: str) -> str:
    idx = output.rfind(source_text)
    if idx == -1:
        return output
    return output[idx + len(source_text) :].strip()


def translate_pass1(
    *,
    client: LLMClient,
    model_name: str,
    prompt_template: str,
    source_text: str,
    glossary: str = "",
    alias_resolutions: str = "",
    matched_idioms: str = "",
    continuity_notes: str = "",
) -> str:
    prompt = render_named_sections(
        prompt_template,
        sections={
            "GLOSSARY": glossary,
            "ALIAS_RESOLUTIONS": alias_resolutions,
            "MATCHED_IDIOMS": matched_idioms,
            "CONTINUITY_NOTES": continuity_notes,
            "SOURCE_TEXT": source_text,
        },
    )
    raw_output = client.generate_text(model_name=model_name, prompt=prompt)
    return _strip_artifacts(raw_output, source_text)

