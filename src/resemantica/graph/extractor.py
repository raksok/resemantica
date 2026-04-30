from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable

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
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections


_CHAPTER_FILE_RE = re.compile(r"chapter-(\d+)\.json$")
_PLACEHOLDER_RE = re.compile(r"⟦/?[A-Z]+_\d+⟧")

_VALID_ENTITY_TYPES: set[str] = {
    "character", "alias", "title_honorific", "faction", "location",
    "technique", "item_artifact", "realm_concept", "creature_race",
    "generic_role", "event",
}


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
    confidence: float


@dataclass(slots=True)
class _LLMEntity:
    source_term: str
    entity_type: str
    aliases: list[str]
    evidence_snippet: str


@dataclass(slots=True)
class _LLMRelationship:
    type: str
    source_term: str
    target_term: str
    evidence_snippet: str
    confidence: float
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


def _resolve_entity_id(
    normalized_source: str,
    entity_id_by_key: dict[tuple[str, str], str],
) -> str | None:
    for (_cat, norm), eid in entity_id_by_key.items():
        if norm == normalized_source:
            return eid
    return None


def _parse_llm_response(raw: str) -> tuple[list[_LLMEntity], list[_LLMRelationship]]:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")

    entities_raw = parsed.get("entities", [])
    if not isinstance(entities_raw, list):
        entities_raw = []

    entities: list[_LLMEntity] = []
    for item in entities_raw:
        if not isinstance(item, dict):
            continue
        source_term = str(item.get("source_term", "")).strip()
        entity_type = str(item.get("entity_type", "")).strip()
        if not source_term or not entity_type or entity_type not in _VALID_ENTITY_TYPES:
            continue
        aliases_raw = item.get("aliases", [])
        aliases = (
            [str(a) for a in aliases_raw if isinstance(a, str) and a.strip()]
            if isinstance(aliases_raw, list)
            else []
        )
        evidence = str(item.get("evidence_snippet", "")).strip()
        entities.append(_LLMEntity(
            source_term=source_term,
            entity_type=entity_type,
            aliases=aliases,
            evidence_snippet=evidence,
        ))

    rels_raw = parsed.get("relationships", [])
    if not isinstance(rels_raw, list):
        rels_raw = []

    relationships: list[_LLMRelationship] = []
    for item in rels_raw:
        if not isinstance(item, dict):
            continue
        rel_type = str(item.get("type", "")).strip()
        if not rel_type or rel_type not in WORLD_MODEL_EDGE_TYPES:
            continue
        source_term = str(item.get("source_term", "")).strip()
        target_term = str(item.get("target_term", "")).strip()
        if not source_term or not target_term:
            continue
        try:
            confidence = float(item.get("confidence", 0.5))
        except (ValueError, TypeError):
            confidence = 0.5
        lore_text = item.get("lore_text")
        if lore_text is not None:
            lore_text = str(lore_text).strip() or None
        is_masked = bool(item.get("is_masked_identity", False))
        evidence = str(item.get("evidence_snippet", "")).strip()
        relationships.append(_LLMRelationship(
            type=rel_type,
            source_term=source_term,
            target_term=target_term,
            evidence_snippet=evidence,
            confidence=confidence,
            lore_text=lore_text,
            is_masked_identity=is_masked,
        ))

    return entities, relationships


def _append_observation(
    observations: list[_WorldModelObservation],
    *,
    edge_type: str,
    source_entity_ids: list[str],
    target_entity_ids: list[str],
    chapter_number: int,
    lore_text: str | None,
    is_masked_identity: bool,
    confidence: float,
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
                    confidence=confidence,
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
        current_confidence = ordered[0].confidence

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
                    confidence=current_confidence,
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
                current_confidence = max(current_confidence, item.confidence)
                continue
            if item.chapter_number == current_start:
                if current_lore is None and item.lore_text is not None:
                    current_lore = item.lore_text
                current_masked = current_masked or item.is_masked_identity
                current_confidence = max(current_confidence, item.confidence)
                continue

            _flush(item.chapter_number - 1)
            current_target = item.target_entity_id
            current_start = item.chapter_number
            current_lore = item.lore_text
            current_masked = item.is_masked_identity
            current_confidence = item.confidence

        _flush(None)

    return sorted(relationships, key=lambda row: row.relationship_id)


def _build_glossary_context(entries: list[LockedGlossaryEntry]) -> str:
    lines = [f"{e.source_term} | {e.category}" for e in entries]
    return "\n".join(lines) if lines else "(none)"


def extract_entities(
    *,
    release_id: str,
    extracted_chapters_dir: Path,
    locked_glossary: list[LockedGlossaryEntry],
    llm_client: LLMClient,
    model_name: str,
    prompt_template: str,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    skip_chapters: set[int] | None = None,
    event_callback: Callable[[str, int, dict[str, object]], None] | None = None,
) -> GraphExtractionResult:
    tracked_entries = [
        entry
        for entry in locked_glossary
        if entry.category in GRAPH_ENTITY_CATEGORIES
    ]
    glossary_idx: dict[tuple[str, str], LockedGlossaryEntry] = {}
    for entry in tracked_entries:
        key = (entry.category, entry.normalized_source_term)
        glossary_idx[key] = entry

    entities_by_id: dict[str, GraphEntity] = {}
    entity_id_by_key: dict[tuple[str, str], str] = {}
    appearances_by_id: dict[str, GraphAppearance] = {}
    aliases: list[GraphAlias] = []
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

    glossary_context_str = _build_glossary_context(tracked_entries)

    for chapter_file in chapter_files:
        payload = json.loads(chapter_file.read_text(encoding="utf-8"))
        chapter_number = int(payload.get("chapter_number", _chapter_number_from_path(chapter_file)))
        if event_callback is not None:
            event_callback("chapter_started", chapter_number, {})

        if skip_chapters and chapter_number in skip_chapters:
            if event_callback is not None:
                event_callback("chapter_skipped", chapter_number, {"reason": "non_story_chapter"})
            continue

        source_text = _collect_source_text(payload)
        if not source_text:
            if event_callback is not None:
                event_callback("chapter_skipped", chapter_number, {"reason": "empty_source_text"})
            continue

        prompt = render_named_sections(
            prompt_template,
            {
                "CHAPTER_NUMBER": str(chapter_number),
                "SOURCE_TEXT_ZH": source_text,
                "GLOSSARY_CONTEXT": glossary_context_str,
            },
        )

        raw = llm_client.generate_text(model_name=model_name, prompt=prompt)

        try:
            llm_entities, llm_relationships = _parse_llm_response(raw)
        except (json.JSONDecodeError, ValueError):
            warnings.append(f"warning_emitted: LLM parse error chapter={chapter_number}, skipping")
            if event_callback is not None:
                event_callback("chapter_skipped", chapter_number, {"reason": "parse_error"})
            continue

        for llm_ent in llm_entities:
            normalized_source = normalize_term(llm_ent.source_term)
            if not normalized_source:
                continue

            glossary_key = (llm_ent.entity_type, normalized_source)
            glossary_entry = glossary_idx.get(glossary_key)

            if glossary_entry is not None:
                entity_id = _entity_id(
                    release_id=release_id,
                    category=glossary_entry.category,
                    normalized_source=glossary_entry.normalized_source_term,
                )
                entity_id_by_key[glossary_key] = entity_id

                current = entities_by_id.get(entity_id)
                if current is None:
                    if event_callback is not None:
                        event_callback(
                            "entity_extracted",
                            chapter_number,
                            {"entity_name": glossary_entry.target_term},
                        )
                    entities_by_id[entity_id] = GraphEntity(
                        entity_id=entity_id,
                        release_id=release_id,
                        entity_type=glossary_entry.category,
                        canonical_name=glossary_entry.target_term,
                        glossary_entry_id=glossary_entry.glossary_entry_id,
                        first_seen_chapter=chapter_number,
                        last_seen_chapter=chapter_number,
                        revealed_chapter=chapter_number,
                        status="provisional",
                        schema_version=1,
                    )
                else:
                    current.first_seen_chapter = min(current.first_seen_chapter, chapter_number)
                    current.last_seen_chapter = max(current.last_seen_chapter, chapter_number)

            elif llm_ent.entity_type in GLOSSARY_COVERED_CATEGORIES:
                def_key = (llm_ent.entity_type, normalized_source)
                current_deferred = deferred_by_key.get(def_key)
                if current_deferred is None:
                    if event_callback is not None:
                        event_callback(
                            "entity_extracted",
                            chapter_number,
                            {"entity_name": llm_ent.source_term},
                        )
                    deferred_by_key[def_key] = _DeferredAggregate(
                        term_text=llm_ent.source_term,
                        category=llm_ent.entity_type,
                        evidence_snippet=llm_ent.evidence_snippet or _snippet(source_text, llm_ent.source_term),
                        source_chapter=chapter_number,
                        last_seen_chapter=chapter_number,
                        appearance_count=1,
                    )
                    warnings.append(
                        f"warning_emitted: deferred term {llm_ent.source_term!r} category={llm_ent.entity_type} chapter={chapter_number}"
                    )
                else:
                    current_deferred.last_seen_chapter = max(
                        current_deferred.last_seen_chapter, chapter_number
                    )
                    current_deferred.appearance_count += 1
                continue

            else:
                existing_id = _resolve_entity_id(normalized_source, entity_id_by_key)
                if existing_id is not None:
                    existing_key = None
                    for (cat, norm), registered_eid in list(entity_id_by_key.items()):
                        if registered_eid == existing_id:
                            existing_key = (cat, norm)
                            break
                    if existing_key is not None and existing_key[0] != llm_ent.entity_type:
                        warnings.append(
                            f"warning_emitted: type conflict for {llm_ent.source_term!r} "
                            f"(was {existing_key[0]}, LLM says {llm_ent.entity_type}) chapter={chapter_number}"
                        )
                        continue

                entity_id = _entity_id(
                    release_id=release_id,
                    category=llm_ent.entity_type,
                    normalized_source=normalized_source,
                )
                entity_id_by_key[(llm_ent.entity_type, normalized_source)] = entity_id

                current = entities_by_id.get(entity_id)
                if current is None:
                    if event_callback is not None:
                        event_callback(
                            "entity_extracted",
                            chapter_number,
                            {"entity_name": llm_ent.source_term},
                        )
                    entities_by_id[entity_id] = GraphEntity(
                        entity_id=entity_id,
                        release_id=release_id,
                        entity_type=llm_ent.entity_type,
                        canonical_name=llm_ent.source_term,
                        glossary_entry_id=None,
                        first_seen_chapter=chapter_number,
                        last_seen_chapter=chapter_number,
                        revealed_chapter=chapter_number,
                        status="provisional",
                        schema_version=1,
                    )
                else:
                    current.first_seen_chapter = min(current.first_seen_chapter, chapter_number)
                    current.last_seen_chapter = max(current.last_seen_chapter, chapter_number)

            eid = _resolve_entity_id(normalized_source, entity_id_by_key)
            if eid is None:
                continue

            appearance_id = _appearance_id(
                release_id=release_id,
                entity_id=eid,
                chapter_number=chapter_number,
            )
            if appearance_id not in appearances_by_id:
                appearances_by_id[appearance_id] = GraphAppearance(
                    appearance_id=appearance_id,
                    release_id=release_id,
                    entity_id=eid,
                    chapter_number=chapter_number,
                    evidence_snippet=llm_ent.evidence_snippet or _snippet(source_text, llm_ent.source_term),
                    status="provisional",
                    schema_version=1,
                )

            for alias_text in llm_ent.aliases:
                alias_id_hash = sha256(f"{release_id}:{eid}:{alias_text}".encode("utf-8")).hexdigest()[:24]
                aliases.append(GraphAlias(
                    alias_id=f"als_{alias_id_hash}",
                    release_id=release_id,
                    entity_id=eid,
                    alias_text=alias_text,
                    alias_language="zh",
                    first_seen_chapter=chapter_number,
                    last_seen_chapter=chapter_number,
                    revealed_chapter=chapter_number,
                    confidence=0.7,
                    is_masked_identity=False,
                    status="provisional",
                    schema_version=1,
                ))

        for llm_rel in llm_relationships:
            src_normalized = normalize_term(llm_rel.source_term)
            tgt_normalized = normalize_term(llm_rel.target_term)
            if not src_normalized or not tgt_normalized:
                continue

            src_eid = _resolve_entity_id(src_normalized, entity_id_by_key)
            tgt_eid = _resolve_entity_id(tgt_normalized, entity_id_by_key)
            if src_eid is None or tgt_eid is None:
                continue

            _append_observation(
                world_model_observations,
                edge_type=llm_rel.type,
                source_entity_ids=[src_eid],
                target_entity_ids=[tgt_eid],
                chapter_number=chapter_number,
                lore_text=llm_rel.lore_text,
                is_masked_identity=llm_rel.is_masked_identity,
                confidence=llm_rel.confidence,
            )
        if event_callback is not None:
            event_callback("chapter_completed", chapter_number, {})

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
        provisional_aliases=aliases,
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
