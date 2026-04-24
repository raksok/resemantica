from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.glossary.validators import normalize_term
from resemantica.graph.models import (
    DeferredEntityRecord,
    GLOSSARY_COVERED_CATEGORIES,
    GraphAlias,
    GraphAppearance,
    GraphEntity,
    GraphRelationship,
)

_CHAPTER_FILE_RE = re.compile(r"chapter-(\d+)\.json$")
_PLACEHOLDER_RE = re.compile(r"⟦/?[A-Z]+_\d+⟧")
_CJK_TERM_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")
_FACTION_SUFFIXES = ("门", "派", "宗", "帮", "盟")
_LOCATION_SUFFIXES = ("山", "城", "宫", "谷", "峰", "州", "国", "镇", "村")


@dataclass(slots=True)
class GraphExtractionResult:
    provisional_entities: list[GraphEntity]
    provisional_aliases: list[GraphAlias]
    provisional_appearances: list[GraphAppearance]
    provisional_relationships: list[GraphRelationship]
    deferred_entities: list[DeferredEntityRecord]
    warnings: list[str]


@dataclass(slots=True)
class _DeferredAggregate:
    term_text: str
    category: str
    evidence_snippet: str
    source_chapter: int
    last_seen_chapter: int
    appearance_count: int


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
    parts = [
        _strip_placeholders(str(row.get("source_text_zh", ""))).strip()
        for row in records
    ]
    return "\n".join(part for part in parts if part)


def _entity_id(*, release_id: str, category: str, normalized_source: str) -> str:
    digest = sha256(f"{release_id}:{category}:{normalized_source}".encode("utf-8")).hexdigest()[:24]
    return f"ent_{digest}"


def _appearance_id(*, release_id: str, entity_id: str, chapter_number: int) -> str:
    digest = sha256(f"{release_id}:{entity_id}:{chapter_number}".encode("utf-8")).hexdigest()[:24]
    return f"app_{digest}"


def _deferred_id(*, release_id: str, category: str, normalized_source: str) -> str:
    digest = sha256(f"{release_id}:{category}:{normalized_source}".encode("utf-8")).hexdigest()[:24]
    return f"def_{digest}"


def _snippet(text: str, term: str) -> str:
    position = text.find(term)
    if position < 0:
        return text[:120]
    start = max(0, position - 30)
    end = min(len(text), position + len(term) + 30)
    return text[start:end]


def _infer_category(term: str) -> str | None:
    if term.endswith(_FACTION_SUFFIXES):
        return "faction"
    if term.endswith(_LOCATION_SUFFIXES):
        return "location"
    if 2 <= len(term) <= 3:
        return "character"
    return None


def extract_entities(
    *,
    release_id: str,
    extracted_chapters_dir: Path,
    locked_glossary: list[LockedGlossaryEntry],
) -> GraphExtractionResult:
    glossary_index = {
        (entry.category, entry.normalized_source_term): entry
        for entry in locked_glossary
        if entry.category in GLOSSARY_COVERED_CATEGORIES
    }
    tracked_entries = sorted(
        glossary_index.values(),
        key=lambda row: (row.category, row.normalized_source_term),
    )

    entities_by_id: dict[str, GraphEntity] = {}
    appearances_by_id: dict[str, GraphAppearance] = {}
    deferred_by_key: dict[tuple[str, str], _DeferredAggregate] = {}
    warnings: list[str] = []

    chapter_files = sorted(
        extracted_chapters_dir.glob("chapter-*.json"),
        key=_chapter_number_from_path,
    )
    for chapter_file in chapter_files:
        payload = json.loads(chapter_file.read_text(encoding="utf-8"))
        chapter_number = int(payload.get("chapter_number", _chapter_number_from_path(chapter_file)))
        source_text = _collect_source_text(payload)
        if not source_text:
            continue

        for entry in tracked_entries:
            count = source_text.count(entry.source_term)
            if count <= 0:
                continue
            entity_id = _entity_id(
                release_id=release_id,
                category=entry.category,
                normalized_source=entry.normalized_source_term,
            )
            current = entities_by_id.get(entity_id)
            if current is None:
                entities_by_id[entity_id] = GraphEntity(
                    entity_id=entity_id,
                    release_id=release_id,
                    entity_type=entry.category,
                    canonical_name=entry.target_term,
                    glossary_entry_id=entry.glossary_entry_id,
                    first_seen_chapter=chapter_number,
                    last_seen_chapter=chapter_number,
                    revealed_chapter=chapter_number,
                    status="provisional",
                    schema_version=1,
                )
            else:
                current.first_seen_chapter = min(current.first_seen_chapter, chapter_number)
                current.last_seen_chapter = max(current.last_seen_chapter, chapter_number)

            appearance_id = _appearance_id(
                release_id=release_id,
                entity_id=entity_id,
                chapter_number=chapter_number,
            )
            appearances_by_id[appearance_id] = GraphAppearance(
                appearance_id=appearance_id,
                release_id=release_id,
                entity_id=entity_id,
                chapter_number=chapter_number,
                evidence_snippet=_snippet(source_text, entry.source_term),
                status="provisional",
                schema_version=1,
            )

        term_counts: dict[str, int] = {}
        for term in _CJK_TERM_RE.findall(source_text):
            term_counts[term] = term_counts.get(term, 0) + 1

        for term, count in term_counts.items():
            category = _infer_category(term)
            if category is None or category not in GLOSSARY_COVERED_CATEGORIES:
                continue
            normalized = normalize_term(term)
            if (category, normalized) in glossary_index:
                continue

            key = (category, normalized)
            current_deferred = deferred_by_key.get(key)
            if current_deferred is None:
                deferred_by_key[key] = _DeferredAggregate(
                    term_text=term,
                    category=category,
                    evidence_snippet=_snippet(source_text, term),
                    source_chapter=chapter_number,
                    last_seen_chapter=chapter_number,
                    appearance_count=count,
                )
                warnings.append(
                    f"warning_emitted: deferred term {term!r} category={category} chapter={chapter_number}"
                )
                continue

            current_deferred.last_seen_chapter = max(current_deferred.last_seen_chapter, chapter_number)
            current_deferred.appearance_count += count

    deferred_entities = [
        DeferredEntityRecord(
            deferred_id=_deferred_id(
                release_id=release_id,
                category=category,
                normalized_source=normalized_source,
            ),
            release_id=release_id,
            term_text=aggregate.term_text,
            normalized_term_text=normalized_source,
            category=category,
            evidence_snippet=aggregate.evidence_snippet,
            source_chapter=aggregate.source_chapter,
            last_seen_chapter=aggregate.last_seen_chapter,
            appearance_count=aggregate.appearance_count,
            status="pending_glossary",
            glossary_entry_id=None,
            schema_version=1,
        )
        for (category, normalized_source), aggregate in sorted(deferred_by_key.items())
    ]

    return GraphExtractionResult(
        provisional_entities=sorted(entities_by_id.values(), key=lambda row: row.entity_id),
        provisional_aliases=[],
        provisional_appearances=sorted(
            appearances_by_id.values(),
            key=lambda row: (row.chapter_number, row.appearance_id),
        ),
        provisional_relationships=[],
        deferred_entities=deferred_entities,
        warnings=warnings,
    )

