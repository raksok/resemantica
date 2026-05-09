from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from resemantica.chapters.manifest import ChapterRef
from resemantica.idioms.candidate_gen import (
    RawIdiomCandidate,
    generate_chapter_idiom_candidates,
    merge_across_chapters,
)
from resemantica.idioms.corpus_stats import score_idiom_candidates
from resemantica.idioms.evaluator import evaluate_idiom_candidate_batch
from resemantica.idioms.models import IdiomCandidate
from resemantica.idioms.validators import apply_deterministic_filter
from resemantica.llm.client import LLMClient
from resemantica.orchestration.stop import StopToken, raise_if_stop_requested
from resemantica.settings import AppConfig
from resemantica.utils import _chapter_number_from_path

_CHAPTER_FILE_RE = re.compile(r"chapter-(\d+)\.json$")
_PLACEHOLDER_RE = re.compile(r"⟦/?[A-Z]+_\d+⟧")


@dataclass(slots=True)
class _DetectedIdiom:
    source_text: str
    meaning_zh: str
    usage_notes: str | None


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


def _parse_detected_idioms(raw: str) -> list[_DetectedIdiom]:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    parsed = json.loads(raw)
    rows: object = parsed
    if isinstance(parsed, dict):
        rows = parsed.get("idioms", [])
    if not isinstance(rows, list):
        raise ValueError("idiom_detect output must be a list or {'idioms': [...]} object")

    detected: list[_DetectedIdiom] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_text = str(row.get("source_text", "")).strip()
        meaning_zh = str(row.get("meaning_zh", "")).strip()
        usage_raw = row.get("usage_notes")
        usage_notes: str | None = None
        if isinstance(usage_raw, str) and usage_raw.strip():
            usage_notes = usage_raw.strip()
        if not source_text:
            continue
        detected.append(
            _DetectedIdiom(
                source_text=source_text,
                meaning_zh=meaning_zh,
                usage_notes=usage_notes,
            )
        )
    return detected


def _evidence_snippet(text: str, term: str) -> str:
    position = text.find(term)
    if position < 0:
        return text[:120]
    start = max(0, position - 30)
    end = min(len(text), position + len(term) + 30)
    return text[start:end]


def _candidate_id(
    *,
    release_id: str,
    detection_run_id: str,
    chapter_number: int,
    row_index: int,
    normalized_source_text: str,
) -> str:
    digest = sha256(
        (
            f"{release_id}:{detection_run_id}:{chapter_number}:{row_index}:{normalized_source_text}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    return f"ican_{digest}"


def extract_idioms(
    *,
    release_id: str,
    extracted_chapters_dir: Path,
    detection_run_id: str,
    llm_client: LLMClient,
    model_name: str,
    prompt_template: str,
    prompt_version: str,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    skip_chapters: set[int] | None = None,
    config: AppConfig | None = None,
    chapter_refs: list[ChapterRef] | None = None,
    cache_root: Path | None = None,
    event_callback: Callable[[str, int, dict[str, object]], None] | None = None,
    stop_token: StopToken | None = None,
    skip_llm_eval: bool = False,
    eval_batch_size: int = 50,
    score_threshold: float | None = None,
) -> list[IdiomCandidate]:
    refs = chapter_refs
    if refs is None:
        chapter_files = sorted(
            extracted_chapters_dir.glob("chapter-*.json"),
            key=_chapter_number_from_path,
        )
        if chapter_start is not None or chapter_end is not None:
            chapter_files = [
                f for f in chapter_files
                if (chapter_start is None or _chapter_number_from_path(f) >= chapter_start)
                and (chapter_end is None or _chapter_number_from_path(f) <= chapter_end)
            ]
        refs = [
            ChapterRef(
                chapter_number=_chapter_number_from_path(path),
                chapter_path=path,
                placeholder_path=path,
                source_document_path=None,
                chapter_source_hash=None,
            )
            for path in chapter_files
        ]
    merged_raw: dict[str, RawIdiomCandidate] = {}

    for chapter_ref in refs:
        chapter_file = chapter_ref.chapter_path
        payload = json.loads(chapter_file.read_text(encoding="utf-8"))
        chapter_number = int(payload.get("chapter_number", chapter_ref.chapter_number))
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "completed_chapters": sorted(
                    {row.first_seen_chapter for row in merged_raw.values()}
                )
            },
            message="Idiom extraction stopped before next chapter",
        )
        if event_callback is not None:
            event_callback("chapter_started", chapter_number, {})

        if skip_chapters and chapter_number in skip_chapters:
            if event_callback is not None:
                event_callback("chapter_skipped", chapter_number, {"reason": "non_story_chapter"})
            continue

        source_text_zh = _collect_source_text(payload)
        if not source_text_zh:
            if event_callback is not None:
                event_callback("chapter_skipped", chapter_number, {"reason": "empty_source_text"})
            continue

        chapter_candidates = generate_chapter_idiom_candidates(
            chapter_number=chapter_number,
            source_text=source_text_zh,
        )
        merge_across_chapters(merged_raw, chapter_candidates)
        if event_callback is not None:
            event_callback(
                "chapter_completed",
                chapter_number,
                {
                    "candidate_count": len(chapter_candidates),
                },
            )
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "completed_chapters": sorted(
                    {row.first_seen_chapter for row in merged_raw.values()}
                )
            },
            message=f"Idiom extraction stopped after chapter {chapter_number}",
        )

    candidates: list[IdiomCandidate] = []
    for index, scored in enumerate(score_idiom_candidates(list(merged_raw.values()))):
        raw = scored.raw
        candidates.append(
            IdiomCandidate(
                candidate_id=_candidate_id(
                    release_id=release_id,
                    detection_run_id=detection_run_id,
                    chapter_number=raw.first_seen_chapter,
                    row_index=index,
                    normalized_source_text=raw.normalized_form,
                ),
                release_id=release_id,
                source_text=raw.surface_form,
                normalized_source_text=raw.normalized_form,
                meaning_zh=raw.idiomatic_meaning_zh,
                meaning_en="",
                preferred_rendering_en="",
                usage_notes=None,
                first_seen_chapter=raw.first_seen_chapter,
                last_seen_chapter=raw.last_seen_chapter,
                appearance_count=raw.appearances,
                evidence_snippet=raw.context_snippets[0] if raw.context_snippets else "",
                detection_run_id=detection_run_id,
                candidate_status="discovered",
                validation_status="pending",
                conflict_reason=None,
                analyst_model_name=model_name,
                analyst_prompt_version=prompt_version,
                schema_version=1,
                dictionary_match=1 if raw.dictionary_match else 0,
                source_strategies=json.dumps(sorted(raw.strategies), ensure_ascii=False),
                chapter_coverage=scored.chapter_coverage,
                corpus_score=scored.composite_score,
                context_snippets=json.dumps(raw.context_snippets, ensure_ascii=False),
                literal_meaning_zh=raw.literal_meaning_zh,
                idiomatic_meaning_zh=raw.idiomatic_meaning_zh,
            )
        )

    apply_deterministic_filter(
        candidates,
        min_score=0.2 if score_threshold is None else score_threshold,
    )

    if not skip_llm_eval:
        pending_eval = [candidate for candidate in candidates if candidate.candidate_status == "discovered"]
        eval_results = evaluate_idiom_candidate_batch(
            candidates=pending_eval,
            llm_client=llm_client,
            model_name=model_name,
            prompt_template=prompt_template,
            prompt_version=prompt_version,
            batch_size=eval_batch_size,
            cache_root=cache_root,
        )
        eval_by_id = {result.candidate_id: result for result in eval_results}
        for candidate in pending_eval:
            result = eval_by_id.get(candidate.candidate_id)
            if result is None:
                continue
            candidate.llm_is_idiom = 1 if result.is_idiom else 0
            candidate.llm_usage_type = result.usage_type
            candidate.llm_translation_strategy = result.translation_strategy
            candidate.llm_reason_code = result.reason_code
            candidate.llm_confidence = result.confidence
            if result.meaning_zh and not candidate.meaning_zh.strip():
                candidate.meaning_zh = result.meaning_zh
            if not result.is_idiom:
                candidate.candidate_status = "llm_rejected"
                candidate.conflict_reason = f"llm_rejected:{result.reason_code}"

    return candidates
