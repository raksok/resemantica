from __future__ import annotations

from hashlib import sha256

from resemantica.db.summary_repo import ValidatedSummaryZhRecord
from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections
from resemantica.summaries._context import _format_glossary_context
from resemantica.utils import _canonical_json


def hash_validated_summary(summary: ValidatedSummaryZhRecord) -> str:
    payload = {
        "summary_id": summary.summary_id,
        "release_id": summary.release_id,
        "chapter_number": summary.chapter_number,
        "summary_type": summary.summary_type,
        "content_zh": summary.content_zh,
        "derived_from_chapter_hash": summary.derived_from_chapter_hash,
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def hash_locked_glossary(entries: list[LockedGlossaryEntry]) -> str:
    payload = [
        {
            "glossary_entry_id": entry.glossary_entry_id,
            "source_term": entry.source_term,
            "target_term": entry.target_term,
            "category": entry.category,
            "status": entry.status,
        }
        for entry in sorted(entries, key=lambda item: item.glossary_entry_id)
    ]
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def build_story_so_far(*, short_summaries: list[ValidatedSummaryZhRecord]) -> str:
    ordered = sorted(short_summaries, key=lambda item: item.chapter_number)
    lines = [f"第{item.chapter_number}章：{item.content_zh.strip()}" for item in ordered if item.content_zh.strip()]
    return "\n".join(lines)


def derive_english_summary(
    *,
    llm_client: LLMClient,
    model_name: str,
    prompt_template: str,
    source_text_zh: str,
    locked_glossary: list[LockedGlossaryEntry],
) -> str:
    prompt = render_named_sections(
        prompt_template,
        sections={
            "SOURCE_TEXT_ZH": source_text_zh,
            "LOCKED_GLOSSARY": _format_glossary_context(locked_glossary),
        },
    )
    return llm_client.generate_text(model_name=model_name, prompt=prompt).strip()
