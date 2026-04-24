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
    GRAPH_ENTITY_CATEGORIES,
    GLOSSARY_COVERED_CATEGORIES,
    GraphAlias,
    GraphAppearance,
    GraphEntity,
    GraphRelationship,
    WORLD_MODEL_EDGE_TYPES,
)

_CHAPTER_FILE_RE = re.compile(r"chapter-(\d+)\.json$")
_PLACEHOLDER_RE = re.compile(r"⟦/?[A-Z]+_\d+⟧")
_CJK_TERM_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")
_FACTION_SUFFIXES = ("门", "派", "宗", "帮", "盟")
_LOCATION_SUFFIXES = ("山", "城", "宫", "谷", "峰", "州", "国", "镇", "村")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？\n]+")
_MEMBER_OF_HINTS = ("弟子", "门人", "加入", "隶属", "归属", "效力")
_LOCATED_IN_HINTS = ("在", "位于", "驻扎", "身处", "来到", "留在", "坐镇")
_HELD_BY_HINTS = ("持有", "获得", "佩戴", "执掌", "拥有", "掌握")
_RANKED_AS_HINTS = ("成为", "晋升", "被封", "任命", "升为", "担任")
_LORE_HINTS = ("其实", "原来", "真实身份", "真身", "秘密")
_MASKED_HINTS = ("真实身份", "真身", "伪装", "假扮")


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


@dataclass(slots=True)
class _WorldModelObservation:
    edge_type: str
    source_entity_id: str
    target_entity_id: str
    chapter_number: int
    lore_text: str | None
    is_masked_identity: bool


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


def _relationship_id(
    *,
    release_id: str,
    edge_type: str,
    source_entity_id: str,
    target_entity_id: str,
    start_chapter: int,
) -> str:
    digest = sha256(
        f"{release_id}:{edge_type}:{source_entity_id}:{target_entity_id}:{start_chapter}".encode("utf-8")
    ).hexdigest()[:24]
    return f"rel_{digest}"


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


def _split_sentences(text: str) -> list[str]:
    return [segment.strip() for segment in _SENTENCE_SPLIT_RE.split(text) if segment.strip()]


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _find_present_entity_ids(
    *,
    sentence: str,
    entries: list[LockedGlossaryEntry],
    entity_id_by_key: dict[tuple[str, str], str],
) -> list[str]:
    present: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        key = (entry.category, entry.normalized_source_term)
        entity_id = entity_id_by_key.get(key)
        if entity_id is None:
            continue
        if entry.source_term not in sentence:
            continue
        if entity_id in seen:
            continue
        present.append(entity_id)
        seen.add(entity_id)
    return present


def _append_observation(
    observations: list[_WorldModelObservation],
    *,
    edge_type: str,
    source_entity_ids: list[str],
    target_entity_ids: list[str],
    chapter_number: int,
    lore_text: str | None,
    is_masked_identity: bool,
) -> None:
    if not source_entity_ids or not target_entity_ids:
        return

    seen_pairs: set[tuple[str, str]] = set()
    for source_entity_id in source_entity_ids:
        for target_entity_id in target_entity_ids:
            if source_entity_id == target_entity_id:
                continue
            pair = (source_entity_id, target_entity_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            observations.append(
                _WorldModelObservation(
                    edge_type=edge_type,
                    source_entity_id=source_entity_id,
                    target_entity_id=target_entity_id,
                    chapter_number=chapter_number,
                    lore_text=lore_text,
                    is_masked_identity=is_masked_identity,
                )
            )


def _build_world_model_relationships(
    *,
    release_id: str,
    observations: list[_WorldModelObservation],
) -> list[GraphRelationship]:
    by_scope: dict[tuple[str, str], list[_WorldModelObservation]] = {}
    for observation in observations:
        if observation.edge_type not in WORLD_MODEL_EDGE_TYPES:
            continue
        by_scope.setdefault((observation.edge_type, observation.source_entity_id), []).append(observation)

    relationships: list[GraphRelationship] = []
    for (edge_type, source_entity_id), group in sorted(by_scope.items()):
        ordered = sorted(
            group,
            key=lambda row: (row.chapter_number, row.target_entity_id),
        )
        if not ordered:
            continue

        current_target = ordered[0].target_entity_id
        current_start = ordered[0].chapter_number
        current_lore = ordered[0].lore_text
        current_masked = ordered[0].is_masked_identity

        def _flush(end_chapter: int | None) -> None:
            relationships.append(
                GraphRelationship(
                    relationship_id=_relationship_id(
                        release_id=release_id,
                        edge_type=edge_type,
                        source_entity_id=source_entity_id,
                        target_entity_id=current_target,
                        start_chapter=current_start,
                    ),
                    release_id=release_id,
                    type=edge_type,
                    source_entity_id=source_entity_id,
                    target_entity_id=current_target,
                    source_chapter=current_start,
                    start_chapter=current_start,
                    end_chapter=end_chapter,
                    revealed_chapter=current_start,
                    confidence=0.7,
                    status="provisional",
                    lore_text=current_lore,
                    is_masked_identity=current_masked,
                    schema_version=1,
                )
            )

        for item in ordered[1:]:
            if item.target_entity_id == current_target:
                if current_lore is None and item.lore_text is not None:
                    current_lore = item.lore_text
                current_masked = current_masked or item.is_masked_identity
                continue
            if item.chapter_number == current_start:
                # Deterministic single-state policy per chapter: keep the first target in sort order.
                if current_lore is None and item.lore_text is not None:
                    current_lore = item.lore_text
                current_masked = current_masked or item.is_masked_identity
                continue

            _flush(item.chapter_number - 1)
            current_target = item.target_entity_id
            current_start = item.chapter_number
            current_lore = item.lore_text
            current_masked = item.is_masked_identity

        _flush(None)

    return sorted(relationships, key=lambda row: row.relationship_id)


def extract_entities(
    *,
    release_id: str,
    extracted_chapters_dir: Path,
    locked_glossary: list[LockedGlossaryEntry],
    chapter_start: int | None = None,
    chapter_end: int | None = None,
) -> GraphExtractionResult:
    tracked_entries = [
        entry
        for entry in locked_glossary
        if entry.category in GRAPH_ENTITY_CATEGORIES
    ]
    glossary_index = {
        (entry.category, entry.normalized_source_term): entry
        for entry in tracked_entries
        if entry.category in GLOSSARY_COVERED_CATEGORIES
    }
    tracked_entries = sorted(
        tracked_entries,
        key=lambda row: (row.category, row.normalized_source_term),
    )
    entries_by_category: dict[str, list[LockedGlossaryEntry]] = {}
    for entry in tracked_entries:
        entries_by_category.setdefault(entry.category, []).append(entry)

    entities_by_id: dict[str, GraphEntity] = {}
    entity_id_by_key: dict[tuple[str, str], str] = {}
    appearances_by_id: dict[str, GraphAppearance] = {}
    world_model_observations: list[_WorldModelObservation] = []
    deferred_by_key: dict[tuple[str, str], _DeferredAggregate] = {}
    warnings: list[str] = []

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
            normalized_source = entry.normalized_source_term
            entity_id = _entity_id(
                release_id=release_id,
                category=entry.category,
                normalized_source=normalized_source,
            )
            entity_id_by_key[(entry.category, normalized_source)] = entity_id
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

        for sentence in _split_sentences(source_text):
            characters = _find_present_entity_ids(
                sentence=sentence,
                entries=entries_by_category.get("character", []),
                entity_id_by_key=entity_id_by_key,
            )
            factions = _find_present_entity_ids(
                sentence=sentence,
                entries=entries_by_category.get("faction", []),
                entity_id_by_key=entity_id_by_key,
            )
            locations = _find_present_entity_ids(
                sentence=sentence,
                entries=entries_by_category.get("location", []),
                entity_id_by_key=entity_id_by_key,
            )
            items = _find_present_entity_ids(
                sentence=sentence,
                entries=entries_by_category.get("item_artifact", [])
                + entries_by_category.get("technique", []),
                entity_id_by_key=entity_id_by_key,
            )
            ranks = _find_present_entity_ids(
                sentence=sentence,
                entries=entries_by_category.get("title_honorific", [])
                + entries_by_category.get("generic_role", []),
                entity_id_by_key=entity_id_by_key,
            )
            locatables = sorted(set(characters + factions + items))
            lore_text = sentence if _contains_any(sentence, _LORE_HINTS) else None
            is_masked_identity = _contains_any(sentence, _MASKED_HINTS)

            if _contains_any(sentence, _MEMBER_OF_HINTS):
                _append_observation(
                    world_model_observations,
                    edge_type="MEMBER_OF",
                    source_entity_ids=characters,
                    target_entity_ids=factions,
                    chapter_number=chapter_number,
                    lore_text=lore_text,
                    is_masked_identity=is_masked_identity,
                )
            if _contains_any(sentence, _LOCATED_IN_HINTS):
                _append_observation(
                    world_model_observations,
                    edge_type="LOCATED_IN",
                    source_entity_ids=locatables,
                    target_entity_ids=locations,
                    chapter_number=chapter_number,
                    lore_text=lore_text,
                    is_masked_identity=is_masked_identity,
                )
            if _contains_any(sentence, _HELD_BY_HINTS):
                _append_observation(
                    world_model_observations,
                    edge_type="HELD_BY",
                    source_entity_ids=items,
                    target_entity_ids=characters,
                    chapter_number=chapter_number,
                    lore_text=lore_text,
                    is_masked_identity=is_masked_identity,
                )
            if _contains_any(sentence, _RANKED_AS_HINTS):
                _append_observation(
                    world_model_observations,
                    edge_type="RANKED_AS",
                    source_entity_ids=characters,
                    target_entity_ids=ranks,
                    chapter_number=chapter_number,
                    lore_text=lore_text,
                    is_masked_identity=is_masked_identity,
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
        provisional_relationships=_build_world_model_relationships(
            release_id=release_id,
            observations=world_model_observations,
        ),
        deferred_entities=deferred_entities,
        warnings=warnings,
    )
