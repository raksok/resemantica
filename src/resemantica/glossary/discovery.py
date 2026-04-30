from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable

from resemantica.glossary.models import GlossaryCandidate
from resemantica.glossary.validators import normalize_term
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections

_CHAPTER_FILE_RE = re.compile(r"chapter-(\d+)\.json$")
_PLACEHOLDER_RE = re.compile(r"⟦/?[A-Z]+_\d+⟧")


@dataclass(slots=True)
class _DetectedTerm:
    source_term: str
    category: str
    evidence_snippet: str


def _chapter_number_from_path(path: Path) -> int:
    match = _CHAPTER_FILE_RE.search(path.name)
    if match is None:
        raise ValueError(f"Unexpected chapter filename: {path.name}")
    return int(match.group(1))


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


def _parse_detected_terms(raw: str) -> list[_DetectedTerm]:
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
        rows = parsed.get("glossary_terms", [])
    if not isinstance(rows, list):
        raise ValueError("glossary_discover output must be a list or {'glossary_terms': [...]} object")

    detected: list[_DetectedTerm] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_term = str(row.get("source_term", "")).strip()
        category = str(row.get("category", "generic_role")).strip()
        evidence = str(row.get("evidence_snippet", "")).strip()
        if not source_term:
            continue
        detected.append(
            _DetectedTerm(
                source_term=source_term,
                category=category,
                evidence_snippet=evidence,
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
    discovery_run_id: str,
    chapter_number: int,
    row_index: int,
    normalized_source_term: str,
    category: str,
) -> str:
    digest = sha256(
        (
            f"{release_id}:{discovery_run_id}:{chapter_number}:{row_index}:{normalized_source_term}:{category}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    return f"gcan_{digest}"


def discover_candidates_from_extracted(
    *,
    release_id: str,
    extracted_chapters_dir: Path,
    discovery_run_id: str,
    llm_client: LLMClient,
    model_name: str,
    prompt_template: str,
    prompt_version: str,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    event_callback: Callable[[str, int, dict[str, object]], None] | None = None,
) -> list[GlossaryCandidate]:
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
    candidates: list[GlossaryCandidate] = []

    for chapter_file in chapter_files:
        payload = json.loads(chapter_file.read_text(encoding="utf-8"))
        chapter_number = int(payload.get("chapter_number", _chapter_number_from_path(chapter_file)))
        if event_callback is not None:
            event_callback("chapter_started", chapter_number, {})
        source_text_zh = _collect_source_text(payload)
        if not source_text_zh:
            if event_callback is not None:
                event_callback("chapter_skipped", chapter_number, {"reason": "empty_source_text"})
            continue

        prompt = render_named_sections(
            prompt_template,
            {
                "CHAPTER_NUMBER": str(chapter_number),
                "SOURCE_TEXT_ZH": source_text_zh,
            },
        )
        raw = llm_client.generate_text(model_name=model_name, prompt=prompt).strip()
        try:
            detected_rows = _parse_detected_terms(raw)
        except json.JSONDecodeError:
            print(f"  WARN: chapter {chapter_number}: JSON decode error, skipping")
            if event_callback is not None:
                event_callback("chapter_skipped", chapter_number, {"reason": "json_decode_error"})
            continue
        except ValueError:
            print(f"  WARN: chapter {chapter_number}: parse error, skipping")
            if event_callback is not None:
                event_callback("chapter_skipped", chapter_number, {"reason": "parse_error"})
            continue

        for index, detected in enumerate(detected_rows):
            normalized_source = normalize_term(detected.source_term)
            if not normalized_source:
                continue
            if event_callback is not None:
                event_callback(
                    "term_found",
                    chapter_number,
                    {"term": detected.source_term, "category": detected.category},
                )
            appearance_count = max(1, source_text_zh.count(detected.source_term))
            snippet = detected.evidence_snippet or _evidence_snippet(source_text_zh, detected.source_term)
            candidates.append(
                GlossaryCandidate(
                    candidate_id=_candidate_id(
                        release_id=release_id,
                        discovery_run_id=discovery_run_id,
                        chapter_number=chapter_number,
                        row_index=index,
                        normalized_source_term=normalized_source,
                        category=detected.category,
                    ),
                    release_id=release_id,
                    source_term=detected.source_term,
                    normalized_source_term=normalized_source,
                    category=detected.category,
                    source_language="zh",
                    first_seen_chapter=chapter_number,
                    last_seen_chapter=chapter_number,
                    appearance_count=appearance_count,
                    evidence_snippet=snippet,
                    candidate_translation_en=None,
                    normalized_target_term=None,
                    discovery_run_id=discovery_run_id,
                    translation_run_id=None,
                    candidate_status="discovered",
                    validation_status="pending",
                    conflict_reason=None,
                    analyst_model_name=model_name,
                    analyst_prompt_version=prompt_version,
                    translator_model_name=None,
                    translator_prompt_version=None,
                    schema_version=1,
                )
            )
        if event_callback is not None:
            event_callback("chapter_completed", chapter_number, {})

    return candidates
