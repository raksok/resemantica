from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from resemantica.chapters.manifest import ChapterRef
from resemantica.glossary.candidate_gen import (
    RawCandidate,
    generate_chapter_candidates,
    merge_across_chapters,
)
from resemantica.glossary.corpus_stats import CorpusStats, score_candidates
from resemantica.glossary.models import GlossaryCandidate
from resemantica.orchestration.stop import StopToken, raise_if_stop_requested

_PLACEHOLDER_RE = re.compile(r"⟦/?[A-Z]+_\d+⟧")


def _strip_placeholders(text: str) -> str:
    return _PLACEHOLDER_RE.sub("", text)


def _collect_source_text(payload: dict[str, Any]) -> str:
    records_raw = payload.get("records", [])
    if not isinstance(records_raw, list):
        raise ValueError("Extracted chapter payload has invalid records field")
    records = sorted(
        records_raw,
        key=lambda row: (
            int(row.get("block_order", 0)),
            int(row.get("segment_order") or 0),
        ),
    )
    lines: list[str] = []
    for record in records:
        text = _strip_placeholders(str(record.get("source_text_zh", ""))).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _candidate_id(
    *,
    release_id: str,
    discovery_run_id: str,
    normalized_source_term: str,
    category: str,
) -> str:
    digest = sha256(
        (f"{release_id}:{discovery_run_id}:{normalized_source_term}:{category}").encode("utf-8")
    ).hexdigest()[:24]
    return f"gcan_{digest}"


def discover_candidates_from_extracted(
    *,
    release_id: str,
    discovery_run_id: str,
    chapter_refs: list[ChapterRef],
    event_callback: Callable[[str, int, dict[str, object]], None] | None = None,
    stop_token: StopToken | None = None,
    # The following parameters are kept for signature compatibility but ignored in deterministic mode
    extracted_chapters_dir: Path | None = None,
    llm_client: Any = None,
    model_name: str | None = None,
    prompt_template: str | None = None,
    prompt_version: str | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    config: Any = None,
    cache_root: Path | None = None,
) -> list[GlossaryCandidate]:
    """
    Deterministic Chapter-by-Chapter extraction + Corpus-level scoring.
    Replaces the old LLM-driven discovery loop.
    """
    # 1. Stage 1: Per-chapter extraction with incremental accumulation
    merged_accumulator: dict[str, RawCandidate] = {}
    term_freq: dict[str, int] = {}
    doc_freq: dict[str, int] = {}
    total_chapters = 0
    total_tokens = 0

    # Track first/last seen chapter
    first_seen: dict[str, int] = {}
    last_seen: dict[str, int] = {}

    for ref in chapter_refs:
        chapter_number = ref.chapter_number
        if event_callback:
            event_callback("chapter_started", chapter_number, {})

        raise_if_stop_requested(stop_token)

        # Load chapter text
        payload = json.loads(ref.chapter_path.read_text(encoding="utf-8"))
        text = _collect_source_text(payload)

        if not text:
            logger.debug("Chapter {}: empty text, skipping", chapter_number)
            if event_callback:
                event_callback("chapter_skipped", chapter_number, {"reason": "empty_text"})
            continue

        logger.debug("Chapter {}: {} chars of source text collected", chapter_number, len(text))

        # Extract candidates for this chapter
        raw_candidates = generate_chapter_candidates(text)

        # Incremental merge into single accumulator dict
        merge_across_chapters(merged_accumulator, raw_candidates)

        # Incremental corpus stats
        chapter_terms: set[str] = set()
        for rc in raw_candidates:
            term_freq[rc.normalized_form] = term_freq.get(rc.normalized_form, 0) + rc.appearances
            total_tokens += rc.appearances
            chapter_terms.add(rc.normalized_form)
        for norm in chapter_terms:
            doc_freq[norm] = doc_freq.get(norm, 0) + 1
        total_chapters += 1

        # Track first/last seen chapter
        for rc in raw_candidates:
            key = f"{rc.normalized_form}:{rc.type_prior}"
            if key not in first_seen or chapter_number < first_seen[key]:
                first_seen[key] = chapter_number
            if key not in last_seen or chapter_number > last_seen[key]:
                last_seen[key] = chapter_number

        # raw_candidates goes out of scope — GC reclaims per-chapter objects
        if event_callback:
            event_callback("chapter_completed", chapter_number, {"term_count": len(raw_candidates)})

    # 2. Stage 2: Corpus Aggregation & Scoring
    stats = CorpusStats(
        term_frequency=term_freq,
        document_frequency=doc_freq,
        total_chapters=total_chapters,
        total_tokens=total_tokens,
    )

    global_raw = list(merged_accumulator.values())
    logger.debug(
        "Corpus aggregation: {} unique terms across {} chapters, scoring...",
        len(global_raw),
        total_chapters,
    )
    scored_list = score_candidates(global_raw, stats)

    # 3. Convert to GlossaryCandidate
    candidates: list[GlossaryCandidate] = []
    for sc in scored_list:
        rc = sc.raw
        key = f"{rc.normalized_form}:{rc.type_prior}"

        candidates.append(
            GlossaryCandidate(
                candidate_id=_candidate_id(
                    release_id=release_id,
                    discovery_run_id=discovery_run_id,
                    normalized_source_term=rc.normalized_form,
                    category=rc.type_prior,
                ),
                release_id=release_id,
                source_term=rc.surface_form,
                normalized_source_term=rc.normalized_form,
                category=rc.type_prior,
                source_language="zh",
                first_seen_chapter=first_seen.get(key, 0),
                last_seen_chapter=last_seen.get(key, 0),
                appearance_count=stats.term_frequency.get(rc.normalized_form, 0),
                evidence_snippet=rc.context_snippets[0] if rc.context_snippets else "",
                candidate_translation_en=None,
                normalized_target_term=None,
                discovery_run_id=discovery_run_id,
                translation_run_id=None,
                candidate_status="discovered",
                validation_status="pending",
                conflict_reason=None,
                critic_score=None,
                pos_tags=",".join(rc.pos_tags) if rc.pos_tags else None,
                ner_label=rc.ner_label,
                type_prior=rc.type_prior,
                source_strategies=",".join(sorted(rc.strategies)) if rc.strategies else None,
                chapter_coverage=stats.document_frequency.get(rc.normalized_form, 0),
                corpus_score=sc.composite_score,
                context_snippets=json.dumps(rc.context_snippets, ensure_ascii=False)
                if rc.context_snippets
                else None,
                schema_version=1,
            )
        )

    return candidates
