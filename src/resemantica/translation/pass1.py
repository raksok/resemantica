from __future__ import annotations

import re

from resemantica.llm.budget import ensure_prompt_within_budget
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections
from resemantica.settings import AppConfig, load_config

_CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")

_COF_RE = re.compile(r"</?think>", re.IGNORECASE)
_COF_CONTENT_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_COF_RE2 = re.compile(r"</?thought>", re.IGNORECASE)
_COF_CONTENT_RE2 = re.compile(r"<thought>.*?</thought>", re.IGNORECASE | re.DOTALL)

_LABEL_PREFIX_RE = re.compile(
    r"^(Category|Translation|Term|Evidence|Output|Result|English)\s*:\s*",
    re.IGNORECASE | re.MULTILINE,
)

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"\*(.+?)\*")
_CONTENT_RETRY_COUNT = 2
_ENGLISH_ONLY_CORRECTION = """

## CORRECTION
The previous response was empty or contained Chinese text. Translate the SOURCE_TEXT completely into
English only. Preserve every placeholder exactly and return only the non-empty English translation.
""".strip()


def _clean_pass1_response(text: str) -> str:
    text = _COF_CONTENT_RE.sub("", text).strip()
    text = _COF_CONTENT_RE2.sub("", text).strip()

    text = _COF_RE.sub("", text).strip()
    text = _COF_RE2.sub("", text).strip()

    text = _LABEL_PREFIX_RE.sub("", text).strip()

    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)

    text = text.strip('\u201c\u201d\u2018\u2019"\u2019')

    if _CHINESE_CHAR_RE.search(text):
        return ""

    return text


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
    config: AppConfig | None = None,
    chapter_number: int | None = None,
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
    ensure_prompt_within_budget(
        prompt,
        config=config or load_config(),
        stage_name="translate.pass1",
        chapter_number=chapter_number,
    )
    active_prompt = prompt
    for attempt in range(_CONTENT_RETRY_COUNT + 1):
        raw_output = client.generate_text(model_name=model_name, prompt=active_prompt)
        stripped = _strip_artifacts(raw_output, source_text)
        cleaned = _clean_pass1_response(stripped)
        if cleaned or attempt == _CONTENT_RETRY_COUNT:
            return cleaned
        active_prompt = f"{prompt}\n\n{_ENGLISH_ONLY_CORRECTION}"
        ensure_prompt_within_budget(
            active_prompt,
            config=config or load_config(),
            stage_name="translate.pass1",
            chapter_number=chapter_number,
        )
    return ""
