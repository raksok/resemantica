from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from resemantica.chapters.manifest import ChapterRef
from resemantica.idioms.models import IdiomCandidate
from resemantica.idioms.validators import normalize_idiom_source
from resemantica.llm.budget import (
    PromptBudgetError,
    chunk_text_for_prompt,
    ensure_prompt_within_budget,
)
from resemantica.llm.cache import LLMCacheIdentity, hash_prompt, load_cached_text, save_cached_text
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections
from resemantica.llm.tokens import count_tokens
from resemantica.orchestration.stop import StopToken, raise_if_stop_requested
from resemantica.settings import AppConfig, load_config
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
) -> list[IdiomCandidate]:
    config_obj = config or load_config()
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
    candidates: list[IdiomCandidate] = []

    for chapter_ref in refs:
        chapter_file = chapter_ref.chapter_path
        payload = json.loads(chapter_file.read_text(encoding="utf-8"))
        chapter_number = int(payload.get("chapter_number", chapter_ref.chapter_number))
        raise_if_stop_requested(
            stop_token,
            checkpoint={"completed_chapters": sorted({row.first_seen_chapter for row in candidates})},
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

        static_prompt = render_named_sections(
            prompt_template,
            {
                "CHAPTER_NUMBER": str(chapter_number),
                "SOURCE_TEXT_ZH": "",
            },
        )
        try:
            chunks = chunk_text_for_prompt(
                source_text_zh,
                config=config_obj,
                static_prompt_tokens=count_tokens(static_prompt),
            )
        except PromptBudgetError:
            if event_callback is not None:
                event_callback("chapter_skipped", chapter_number, {"reason": "prompt_budget_exceeded"})
            continue

        detected_rows: list[_DetectedIdiom] = []
        chapter_skipped = False
        for chunk in chunks:
            chunk_text = (
                source_text_zh
                if chunk.chunk_count == 1
                else f"[Chunk {chunk.chunk_index}/{chunk.chunk_count}]\n{chunk.text}"
            )
            prompt = render_named_sections(
                prompt_template,
                {
                    "CHAPTER_NUMBER": str(chapter_number),
                    "SOURCE_TEXT_ZH": chunk_text,
                },
            )
            try:
                ensure_prompt_within_budget(
                    prompt,
                    config=config_obj,
                    stage_name="preprocess-idioms.detect",
                    chapter_number=chapter_number,
                )
            except PromptBudgetError:
                if event_callback is not None:
                    event_callback("chapter_skipped", chapter_number, {"reason": "prompt_budget_exceeded"})
                chapter_skipped = True
                break

            identity = LLMCacheIdentity(
                release_id=release_id,
                chapter_number=chapter_number,
                source_hash=str(payload.get("chapter_source_hash") or ""),
                stage_name="preprocess-idioms.detect",
                chunk_index=chunk.chunk_index,
                model_name=model_name,
                prompt_version=prompt_version,
                prompt_hash=hash_prompt(prompt),
            )
            cached = load_cached_text(cache_root, identity) if cache_root is not None else None
            raw = (
                cached
                if cached is not None
                else llm_client.generate_text(model_name=model_name, prompt=prompt).strip()
            )
            if cache_root is not None and cached is None:
                save_cached_text(cache_root, identity, raw)
            try:
                parsed_rows = _parse_detected_idioms(raw)
            except json.JSONDecodeError:
                if cached is not None:
                    assert cache_root is not None
                    raw = llm_client.generate_text(model_name=model_name, prompt=prompt).strip()
                    save_cached_text(cache_root, identity, raw)
                    try:
                        parsed_rows = _parse_detected_idioms(raw)
                    except (json.JSONDecodeError, ValueError):
                        print(f"  WARN: chapter {chapter_number}: JSON decode error, skipping")
                        if event_callback is not None:
                            event_callback("chapter_skipped", chapter_number, {"reason": "json_decode_error"})
                        chapter_skipped = True
                        break
                    detected_rows.extend(parsed_rows)
                    continue
                print(f"  WARN: chapter {chapter_number}: JSON decode error, skipping")
                if event_callback is not None:
                    event_callback("chapter_skipped", chapter_number, {"reason": "json_decode_error"})
                chapter_skipped = True
                break
            except ValueError:
                if cached is not None:
                    assert cache_root is not None
                    raw = llm_client.generate_text(model_name=model_name, prompt=prompt).strip()
                    save_cached_text(cache_root, identity, raw)
                    try:
                        parsed_rows = _parse_detected_idioms(raw)
                    except (json.JSONDecodeError, ValueError):
                        print(f"  WARN: chapter {chapter_number}: parse error, skipping")
                        if event_callback is not None:
                            event_callback("chapter_skipped", chapter_number, {"reason": "parse_error"})
                        chapter_skipped = True
                        break
                    detected_rows.extend(parsed_rows)
                    continue
                print(f"  WARN: chapter {chapter_number}: parse error, skipping")
                if event_callback is not None:
                    event_callback("chapter_skipped", chapter_number, {"reason": "parse_error"})
                chapter_skipped = True
                break
            detected_rows.extend(parsed_rows)
        if chapter_skipped:
            continue

        for index, detected in enumerate(detected_rows):
            normalized_source = normalize_idiom_source(detected.source_text)
            if not normalized_source:
                continue
            appearance_count = max(1, source_text_zh.count(detected.source_text))
            candidates.append(
                IdiomCandidate(
                    candidate_id=_candidate_id(
                        release_id=release_id,
                        detection_run_id=detection_run_id,
                        chapter_number=chapter_number,
                        row_index=index,
                        normalized_source_text=normalized_source,
                    ),
                    release_id=release_id,
                    source_text=detected.source_text,
                    normalized_source_text=normalized_source,
                    meaning_zh=detected.meaning_zh,
                    preferred_rendering_en="",
                    usage_notes=detected.usage_notes,
                    first_seen_chapter=chapter_number,
                    last_seen_chapter=chapter_number,
                    appearance_count=appearance_count,
                    evidence_snippet=_evidence_snippet(source_text_zh, detected.source_text),
                    detection_run_id=detection_run_id,
                    candidate_status="discovered",
                    validation_status="pending",
                    conflict_reason=None,
                    analyst_model_name=model_name,
                    analyst_prompt_version=prompt_version,
                    schema_version=1,
                )
            )
        if event_callback is not None:
            event_callback("chapter_completed", chapter_number, {})
        raise_if_stop_requested(
            stop_token,
            checkpoint={"completed_chapters": sorted({row.first_seen_chapter for row in candidates})},
            message=f"Idiom extraction stopped after chapter {chapter_number}",
        )

    return candidates
