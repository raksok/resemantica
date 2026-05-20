from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from resemantica.db.summary_repo import ValidatedSummaryZhRecord
from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.llm.cache import LLMCacheIdentity, hash_prompt, load_cached_text, save_cached_text
from resemantica.llm.client import LLMClient, record_cache_hit
from resemantica.llm.prompts import render_named_sections
from resemantica.llm.tokens import count_tokens
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


def _render_story_compact_repair_prompt(
    *,
    previous_story_so_far_zh_compact: str,
    chapter_summary_zh_short: str,
    over_budget_text: str,
    token_count: int,
    max_tokens: int,
) -> str:
    return render_named_sections(
        """SUMMARY_STORY_REPAIR

## ANALYST INSTRUCTION
Return only the corrected Chinese compact continuity summary.

## PREVIOUS STORY SO FAR ZH COMPACT
{PREVIOUS_STORY_SO_FAR_ZH_COMPACT}

## CURRENT CHAPTER SUMMARY ZH SHORT
{CHAPTER_SUMMARY_ZH_SHORT}

## OVER-BUDGET DRAFT
{OVER_BUDGET_DRAFT}

## TOKEN BUDGET
current={CURRENT_TOKEN_COUNT}
maximum={STORY_COMPACT_MAX_TOKENS}

## INSTRUCTIONS
Rewrite the over-budget draft into dense Chinese prose under the maximum token budget.
Preserve unresolved plot threads, active character/faction/location state, relationship changes, important terms,
and active risks.
Remove resolved detail, repetition, markdown, headings, explanations, analysis, and chain-of-thought.
""",
        sections={
            "PREVIOUS_STORY_SO_FAR_ZH_COMPACT": previous_story_so_far_zh_compact.strip(),
            "CHAPTER_SUMMARY_ZH_SHORT": chapter_summary_zh_short.strip(),
            "OVER_BUDGET_DRAFT": over_budget_text.strip(),
            "CURRENT_TOKEN_COUNT": str(token_count),
            "STORY_COMPACT_MAX_TOKENS": str(max_tokens),
        },
    )


def compact_story_so_far(
    *,
    llm_client: LLMClient,
    release_id: str,
    chapter_number: int,
    model_name: str,
    prompt_template: str,
    prompt_version: str,
    previous_story_so_far_zh_compact: str,
    chapter_summary_zh_short: str,
    max_tokens: int,
    cache_root: Path | None,
) -> tuple[str, str]:
    source_text = (
        previous_story_so_far_zh_compact.strip()
        + "\n"
        + chapter_summary_zh_short.strip()
    ).strip()
    source_hash = sha256(source_text.encode("utf-8")).hexdigest()
    prompt = render_named_sections(
        prompt_template,
        sections={
            "PREVIOUS_STORY_SO_FAR_ZH_COMPACT": previous_story_so_far_zh_compact.strip(),
            "CHAPTER_SUMMARY_ZH_SHORT": chapter_summary_zh_short.strip(),
            "STORY_COMPACT_MAX_TOKENS": str(max_tokens),
        },
    )
    identity = LLMCacheIdentity(
        release_id=release_id,
        chapter_number=chapter_number,
        source_hash=source_hash,
        stage_name="preprocess-summaries.story-compact",
        chunk_index=1,
        model_name=model_name,
        prompt_version=prompt_version,
        prompt_hash=hash_prompt(prompt),
    )
    cached = load_cached_text(cache_root, identity) if cache_root is not None else None
    if cached is not None:
        record_cache_hit(llm_client)
    compact = (
        cached
        if cached is not None
        else llm_client.generate_text(model_name=model_name, prompt=prompt).strip()
    )
    if not compact.strip():
        raise ValueError("story_so_far_zh_compact generation returned empty text")
    token_count = count_tokens(compact)
    for _attempt in range(2):
        if token_count <= max_tokens:
            compact = compact.strip()
            if cache_root is not None and (cached is None or compact != cached):
                save_cached_text(cache_root, identity, compact)
            return compact, source_hash
        repair_prompt = _render_story_compact_repair_prompt(
            previous_story_so_far_zh_compact=previous_story_so_far_zh_compact,
            chapter_summary_zh_short=chapter_summary_zh_short,
            over_budget_text=compact,
            token_count=token_count,
            max_tokens=max_tokens,
        )
        compact = llm_client.generate_text(model_name=model_name, prompt=repair_prompt).strip()
        if not compact:
            raise ValueError("story_so_far_zh_compact generation returned empty text")
        token_count = count_tokens(compact)
    raise ValueError(
        "story_so_far_zh_compact exceeds configured token budget after repair: "
        f"{token_count} > {max_tokens}"
    )


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
