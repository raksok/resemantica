from __future__ import annotations

import math
from hashlib import sha256
from typing import Any

from resemantica.llm.tokens import count_tokens
from resemantica.packets.models import ChapterPacket, ParagraphBundle
from resemantica.utils import _canonical_json

_GLOSSARY_CATEGORY_PRIORITY = {
    "character": 0,
    "faction": 1,
    "location": 2,
    "item_artifact": 3,
    "technique": 4,
    "realm_concept": 5,
    "creature_race": 6,
    "title_honorific": 7,
    "event": 8,
    "idiom": 9,
    "alias": 10,
    "generic_role": 11,
}


def _normalized(text: str) -> str:
    return text.strip().lower()


def _bundle_size_bytes(bundle: ParagraphBundle) -> int:
    return len(_canonical_json(bundle.to_json_dict()).encode("utf-8"))


def _bundle_reference(record: dict[str, object]) -> str:
    segment_id = record.get("segment_id")
    if isinstance(segment_id, str) and segment_id.strip():
        return segment_id.strip()
    return str(record["block_id"])


def _compact_row(row: dict[str, object], fields: tuple[str, ...]) -> dict[str, object]:
    compact: dict[str, object] = {}
    for field in fields:
        value = row.get(field)
        if value not in (None, "", [], {}):
            compact[field] = value
    return compact


def _compact_glossary_entry(entry: dict[str, object]) -> dict[str, object]:
    return _compact_row(
        entry,
        (
            "glossary_entry_id",
            "source_term",
            "target_term",
            "category",
        ),
    )


def _compact_idiom_entry(entry: dict[str, object]) -> dict[str, object]:
    return _compact_row(
        entry,
        (
            "idiom_id",
            "source_text",
            "preferred_rendering_en",
            "meaning_en",
            "meaning_zh",
            "usage_notes",
        ),
    )


def _compact_alias_entry(entry: dict[str, object]) -> dict[str, object]:
    return _compact_row(
        entry,
        (
            "alias_id",
            "alias_text",
            "entity_id",
            "entity_name",
        ),
    )


def _compact_relationship_entry(entry: dict[str, object]) -> dict[str, object]:
    return _compact_row(
        entry,
        (
            "relationship_id",
            "type",
            "source_entity_id",
            "target_entity_id",
            "lore_text",
            "is_masked_identity",
        ),
    )


def _source_match_stats(source_text: str, needle: str) -> tuple[int, int]:
    if not needle:
        return 0, len(source_text)
    first = source_text.find(needle)
    if first < 0:
        return 0, len(source_text)
    return source_text.count(needle), first


def _glossary_match_sort_key(source_text: str, entry: dict[str, object]) -> tuple[Any, ...]:
    source_term = str(entry.get("source_term", "")).strip()
    occurrence_count, first_occurrence = _source_match_stats(source_text, source_term)
    return (
        _GLOSSARY_CATEGORY_PRIORITY.get(str(entry.get("category", "")), 99),
        -len(source_term),
        -occurrence_count,
        first_occurrence,
        str(entry.get("source_term", "")),
        str(entry.get("target_term", "")),
        str(entry.get("glossary_entry_id", "")),
    )


def _idiom_match_sort_key(source_text: str, entry: dict[str, object]) -> tuple[Any, ...]:
    source = str(entry.get("source_text", "")).strip()
    occurrence_count, first_occurrence = _source_match_stats(source_text, source)
    return (
        -len(source),
        -occurrence_count,
        first_occurrence,
        str(entry.get("normalized_source_text", "")),
        str(entry.get("source_text", "")),
        str(entry.get("idiom_id", "")),
    )


def _append_trimmed_once(bundle: ParagraphBundle, field_name: str) -> None:
    if field_name not in bundle.trimmed_sections:
        bundle.trimmed_sections.append(field_name)


def _select_glossary_matches(
    *,
    source_text: str,
    glossary_subset: list[dict[str, object]],
) -> list[dict[str, object]]:
    matches = [
        entry
        for entry in glossary_subset
        if str(entry.get("source_term", "")).strip()
        and str(entry["source_term"]) in source_text
    ]
    return [
        _compact_glossary_entry(entry)
        for entry in sorted(matches, key=lambda row: _glossary_match_sort_key(source_text, row))
    ]


def _select_idiom_matches(
    *,
    source_text: str,
    idiom_subset: list[dict[str, object]],
) -> list[dict[str, object]]:
    matches = [
        policy
        for policy in idiom_subset
        if str(policy.get("source_text", "")).strip()
        and str(policy["source_text"]) in source_text
    ]
    return [
        _compact_idiom_entry(entry)
        for entry in sorted(matches, key=lambda row: _idiom_match_sort_key(source_text, row))
    ]


def _select_alias_resolutions(
    *,
    source_text: str,
    alias_candidates: list[dict[str, object]],
    blocked_terms: set[str],
) -> tuple[list[dict[str, object]], int]:
    kept: list[dict[str, object]] = []
    blocked_count = 0
    for candidate in alias_candidates:
        alias_text = str(candidate.get("alias_text", ""))
        if not alias_text or alias_text not in source_text:
            continue
        if _normalized(alias_text) in blocked_terms:
            blocked_count += 1
            continue
        kept.append(_compact_alias_entry(candidate))
    return sorted(kept, key=lambda row: str(row.get("alias_text", ""))), blocked_count


def _select_local_relationships(
    *,
    relationships: list[dict[str, object]],
    entity_ids: set[str],
) -> list[dict[str, object]]:
    selected = [
        _compact_relationship_entry(row)
        for row in relationships
        if str(row.get("source_entity_id", "")) in entity_ids
        or str(row.get("target_entity_id", "")) in entity_ids
    ]
    return sorted(selected, key=lambda row: str(row.get("relationship_id", "")))


def build_paragraph_bundle(
    *,
    packet: ChapterPacket,
    block_record: dict[str, object],
    max_bundle_bytes: int,
) -> ParagraphBundle:
    source_text = str(block_record.get("source_text_zh", ""))
    block_ref = _bundle_reference(block_record)

    glossary_matches = _select_glossary_matches(
        source_text=source_text,
        glossary_subset=packet.chapter_glossary_subset,
    )
    idiom_matches = _select_idiom_matches(
        source_text=source_text,
        idiom_subset=packet.chapter_local_idioms,
    )

    blocked_terms = {
        _normalized(str(row.get("source_term", "")))
        for row in glossary_matches
        if str(row.get("source_term", "")).strip()
    }
    blocked_terms |= {
        _normalized(str(row.get("source_text", "")))
        for row in idiom_matches
        if str(row.get("source_text", "")).strip()
    }

    alias_resolutions, blocked_graph_aliases = _select_alias_resolutions(
        source_text=source_text,
        alias_candidates=packet.alias_resolution_candidates,
        blocked_terms=blocked_terms,
    )

    glossary_entry_to_entity = {
        str(entity.get("glossary_entry_id")): str(entity.get("entity_id"))
        for entity in packet.entity_context
        if entity.get("glossary_entry_id")
    }
    related_entity_ids = {
        glossary_entry_to_entity.get(str(glossary.get("glossary_entry_id", "")), "")
        for glossary in glossary_matches
    }
    related_entity_ids |= {
        str(alias.get("entity_id", ""))
        for alias in alias_resolutions
    }
    related_entity_ids.discard("")

    local_relationships = _select_local_relationships(
        relationships=packet.relationship_context,
        entity_ids=related_entity_ids,
    )

    continuity_notes = [
        packet.chapter_summary_short,
        packet.story_so_far_summary,
    ]
    if packet.active_arc_summary:
        continuity_notes.append(packet.active_arc_summary)

    retrieval_evidence_summary = [
        f"glossary:{len(glossary_matches)}",
        f"idiom:{len(idiom_matches)}",
        f"graph_alias:{len(alias_resolutions)}",
        f"graph_relationship:{len(local_relationships)}",
    ]

    digest = sha256(f"{packet.packet_id}:{block_ref}".encode("utf-8")).hexdigest()[:24]
    bundle = ParagraphBundle(
        bundle_id=f"bnd_{digest}",
        release_id=packet.release_id,
        chapter_number=packet.chapter_number,
        block_id=block_ref,
        matched_glossary_entries=glossary_matches,
        alias_resolutions=alias_resolutions,
        matched_idioms=idiom_matches,
        local_relationships=local_relationships,
        continuity_notes=continuity_notes,
        retrieval_evidence_summary=retrieval_evidence_summary,
        risk_classification="unscored",
        packet_ref=packet.packet_id,
    )
    if blocked_graph_aliases:
        bundle.retrieval_evidence_summary.append(
            f"graph_alias_blocked_by_authority:{blocked_graph_aliases}"
        )

    clear_order = [
        "local_relationships",
        "alias_resolutions",
        "continuity_notes",
        "retrieval_evidence_summary",
    ]
    for field_name in clear_order:
        size_bytes = _bundle_size_bytes(bundle)
        if size_bytes <= max_bundle_bytes:
            break
        setattr(bundle, field_name, [])
        _append_trimmed_once(bundle, field_name)

    row_trim_order = [
        "matched_idioms",
        "matched_glossary_entries",
    ]
    for field_name in row_trim_order:
        values = getattr(bundle, field_name)
        while values and _bundle_size_bytes(bundle) > max_bundle_bytes:
            values.pop()
            _append_trimmed_once(bundle, field_name)

    bundle.size_bytes = _bundle_size_bytes(bundle)
    if bundle.size_bytes > max_bundle_bytes:
        raise RuntimeError(
            f"bundle_budget_exceeded: chapter={packet.chapter_number}, block={block_ref}"
        )

    raw_token_count = count_tokens(_canonical_json(bundle.to_json_dict()))
    bundle.buffered_token_count = int(math.ceil(raw_token_count * 1.05))
    return bundle
