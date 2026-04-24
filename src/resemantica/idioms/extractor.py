from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from resemantica.idioms.models import IdiomCandidate
from resemantica.idioms.validators import normalize_idiom_source
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections

_CHAPTER_FILE_RE = re.compile(r"chapter-(\d+)\.json$")
_PLACEHOLDER_RE = re.compile(r"⟦/?[A-Z]+_\d+⟧")


@dataclass(slots=True)
class _DetectedIdiom:
    source_text: str
    meaning_zh: str
    preferred_rendering_en: str
    usage_notes: str | None


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


def _parse_detected_idioms(raw: str) -> list[_DetectedIdiom]:
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
        preferred = str(row.get("preferred_rendering_en", "")).strip()
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
                preferred_rendering_en=preferred,
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
) -> list[IdiomCandidate]:
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
    candidates: list[IdiomCandidate] = []

    for chapter_file in chapter_files:
        payload = json.loads(chapter_file.read_text(encoding="utf-8"))
        chapter_number = int(payload.get("chapter_number", _chapter_number_from_path(chapter_file)))
        source_text_zh = _collect_source_text(payload)
        if not source_text_zh:
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
            detected_rows = _parse_detected_idioms(raw)
        except json.JSONDecodeError:
            print(f"  WARN: chapter {chapter_number}: JSON decode error, skipping")
            continue
        except ValueError:
            print(f"  WARN: chapter {chapter_number}: parse error, skipping")
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
                    preferred_rendering_en=detected.preferred_rendering_en,
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
                    prompt_version=prompt_version,
                    schema_version=1,
                )
            )

    return candidates

