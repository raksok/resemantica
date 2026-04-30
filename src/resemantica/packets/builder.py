from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any

from resemantica.db.glossary_repo import ensure_glossary_schema, list_locked_entries
from resemantica.db.graph_repo import ensure_graph_schema, list_graph_snapshots
from resemantica.db.idiom_repo import ensure_idiom_schema, list_policies
from resemantica.db.packet_repo import ensure_packet_schema, get_latest_packet_metadata, save_packet_metadata
from resemantica.db.sqlite import open_connection
from resemantica.db.summary_repo import (
    ensure_summary_schema,
    get_validated_summary,
    list_validated_summaries,
)
from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.graph.client import GraphClient
from resemantica.graph.filters import (
    filter_for_chapter,
    get_revealed_lore,
    select_local_world_model_edges,
)
from resemantica.graph.models import GraphRelationship
from resemantica.idioms.models import IdiomPolicy
from resemantica.llm.tokens import count_tokens
from resemantica.packets.bundler import build_paragraph_bundle
from resemantica.packets.models import ParagraphBundle
from resemantica.packets.invalidation import detect_stale_packet
from resemantica.packets.models import (
    PACKET_BUILDER_VERSION,
    PACKET_SCHEMA_VERSION,
    ChapterPacket,
    PacketBuildOutput,
    PacketMetadataRecord,
)
from resemantica.settings import AppConfig, derive_paths, load_config

_CHAPTER_FILE_RE = re.compile(r"chapter-(\d+)\.json$")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid JSON root in {path}")
    return payload


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _chapter_number_from_path(path: Path) -> int:
    match = _CHAPTER_FILE_RE.search(path.name)
    if match is None:
        raise ValueError(f"Unexpected chapter filename: {path.name}")
    return int(match.group(1))


def _build_graph_client(paths: Any, graph_client: GraphClient | None) -> GraphClient:
    if graph_client is not None:
        return graph_client
    return GraphClient.from_ladybug(db_path=paths.graph_db_path)


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    return 0


def _collect_source_text(records: list[dict[str, object]]) -> str:
    ordered = sorted(
        records,
        key=lambda row: (
            _as_int(row.get("block_order", 0)),
            _as_int(row.get("segment_order") or 0),
        ),
    )
    parts = [str(row.get("source_text_zh", "")) for row in ordered]
    return "\n".join(part for part in parts if part.strip())


def _hash_locked_glossary(entries: list[LockedGlossaryEntry]) -> str:
    payload = [
        {
            "glossary_entry_id": row.glossary_entry_id,
            "source_term": row.source_term,
            "target_term": row.target_term,
            "category": row.category,
            "status": row.status,
        }
        for row in sorted(entries, key=lambda item: item.glossary_entry_id)
    ]
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _hash_summary_rows(rows: list[Any]) -> str:
    payload = [
        {
            "summary_id": row.summary_id,
            "chapter_number": row.chapter_number,
            "summary_type": row.summary_type,
            "content_zh": row.content_zh,
            "derived_from_chapter_hash": row.derived_from_chapter_hash,
        }
        for row in sorted(rows, key=lambda item: (item.chapter_number, item.summary_type, item.summary_id))
    ]
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _hash_idiom_policies(policies: list[IdiomPolicy]) -> str:
    payload = [
        {
            "idiom_id": row.idiom_id,
            "source_text": row.source_text,
            "preferred_rendering_en": row.preferred_rendering_en,
            "policy_status": row.policy_status,
        }
        for row in sorted(policies, key=lambda item: item.idiom_id)
    ]
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _select_glossary_subset(
    *,
    source_text: str,
    locked_glossary: list[LockedGlossaryEntry],
) -> list[LockedGlossaryEntry]:
    matches = [
        entry
        for entry in locked_glossary
        if entry.source_term.strip() and entry.source_term in source_text
    ]
    return sorted(matches, key=lambda row: (row.normalized_source_term, row.category))


def _select_idiom_subset(
    *,
    source_text: str,
    policies: list[IdiomPolicy],
) -> list[IdiomPolicy]:
    matches = [
        policy
        for policy in policies
        if policy.source_text.strip() and policy.source_text in source_text
    ]
    return sorted(matches, key=lambda row: row.normalized_source_text)


def _relationship_context_row(
    *,
    relationship: GraphRelationship,
    entity_names: dict[str, str],
) -> dict[str, object]:
    return {
        "relationship_id": relationship.relationship_id,
        "type": relationship.type,
        "source_entity_id": relationship.source_entity_id,
        "source_name": entity_names.get(relationship.source_entity_id, relationship.source_entity_id),
        "target_entity_id": relationship.target_entity_id,
        "target_name": entity_names.get(relationship.target_entity_id, relationship.target_entity_id),
        "start_chapter": relationship.start_chapter,
        "end_chapter": relationship.end_chapter,
        "revealed_chapter": relationship.revealed_chapter,
        "confidence": relationship.confidence,
    }


def enrich_with_graph_context(
    *,
    chapter_number: int,
    source_text: str,
    glossary_subset: list[LockedGlossaryEntry],
    graph_client: GraphClient,
) -> dict[str, list[dict[str, object]]]:
    entities = graph_client.list_entities(status="confirmed")
    aliases = graph_client.list_aliases(status="confirmed")
    appearances = graph_client.list_appearances(status="confirmed")
    relationships = graph_client.list_relationships(status="confirmed")
    chapter_view = filter_for_chapter(
        entities=entities,
        aliases=aliases,
        appearances=appearances,
        relationships=relationships,
        chapter_number=chapter_number,
    )

    glossary_entry_ids = {row.glossary_entry_id for row in glossary_subset}
    glossary_terms = {
        row.source_term
        for row in glossary_subset
        if row.source_term.strip()
    }
    local_entity_ids = {
        entity.entity_id
        for entity in chapter_view.entities
        if entity.glossary_entry_id is not None and entity.glossary_entry_id in glossary_entry_ids
    }
    local_entity_ids |= {
        alias.entity_id
        for alias in chapter_view.aliases
        if alias.alias_text in source_text
        and alias.alias_text not in glossary_terms
    }
    local_entity_ids |= {
        appearance.entity_id
        for appearance in chapter_view.appearances
        if appearance.chapter_number == chapter_number
    }

    local_entities = [
        entity
        for entity in chapter_view.entities
        if entity.entity_id in local_entity_ids
    ]
    entity_names = {
        entity.entity_id: entity.canonical_name
        for entity in local_entities
    }
    entity_context: list[dict[str, object]] = [
        {
            "entity_id": row.entity_id,
            "entity_type": row.entity_type,
            "canonical_name": row.canonical_name,
            "glossary_entry_id": row.glossary_entry_id,
            "revealed_chapter": row.revealed_chapter,
        }
        for row in sorted(local_entities, key=lambda item: item.entity_id)
    ]

    local_relationships = [
        row
        for row in chapter_view.relationships
        if row.source_entity_id in local_entity_ids and row.target_entity_id in local_entity_ids
    ]
    relationship_context: list[dict[str, object]] = [
        _relationship_context_row(relationship=row, entity_names=entity_names)
        for row in sorted(local_relationships, key=lambda item: item.relationship_id)
    ]

    world_edges = select_local_world_model_edges(
        relationships=chapter_view.relationships,
        chapter_number=chapter_number,
        local_entity_ids=local_entity_ids,
    )
    chapter_safe_relationship_snippets: list[dict[str, object]] = [
        {
            "relationship_id": edge.edge_id,
            "snippet": (
                f"{entity_names.get(edge.source_entity_id, edge.source_entity_id)} "
                f"{edge.edge_type} "
                f"{entity_names.get(edge.target_entity_id, edge.target_entity_id)}"
            ),
            "revealed_chapter": edge.revealed_chapter,
            "is_masked_identity": edge.is_masked_identity,
        }
        for edge in world_edges
    ]

    alias_resolution_candidates: list[dict[str, object]] = [
        {
            "alias_id": row.alias_id,
            "entity_id": row.entity_id,
            "entity_name": entity_names.get(row.entity_id, row.entity_id),
            "alias_text": row.alias_text,
            "revealed_chapter": row.revealed_chapter,
            "is_masked_identity": row.is_masked_identity,
            "confidence": row.confidence,
        }
        for row in sorted(
            [
                alias
                for alias in chapter_view.aliases
                if alias.entity_id in local_entity_ids
            ],
            key=lambda item: item.alias_id,
        )
    ]

    lore_edges = get_revealed_lore(
        relationships=chapter_view.relationships,
        chapter_number=chapter_number,
    )
    reveal_safe_identity_notes: list[dict[str, object]] = [
        {
            "relationship_id": row.edge_id,
            "edge_type": row.edge_type,
            "source_entity_id": row.source_entity_id,
            "target_entity_id": row.target_entity_id,
            "lore_text": row.lore_text,
            "is_masked_identity": row.is_masked_identity,
            "revealed_chapter": row.revealed_chapter,
        }
        for row in lore_edges
        if row.source_entity_id in local_entity_ids or row.target_entity_id in local_entity_ids
    ]

    return {
        "entity_context": entity_context,
        "relationship_context": relationship_context,
        "chapter_safe_relationship_snippets": chapter_safe_relationship_snippets,
        "alias_resolution_candidates": alias_resolution_candidates,
        "reveal_safe_identity_notes": reveal_safe_identity_notes,
    }


def _token_sections(packet: ChapterPacket) -> dict[str, object]:
    return {
        "chapter_glossary_subset": packet.chapter_glossary_subset,
        "previous_3_summaries": packet.previous_3_summaries,
        "story_so_far_summary": packet.story_so_far_summary,
        "chapter_local_idioms": packet.chapter_local_idioms,
        "entity_context": packet.entity_context,
        "relationship_context": packet.relationship_context,
        "chapter_safe_relationship_snippets": packet.chapter_safe_relationship_snippets,
        "alias_resolution_candidates": packet.alias_resolution_candidates,
        "reveal_safe_identity_notes": packet.reveal_safe_identity_notes,
        "warnings": packet.warnings,
    }


def _has_content(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, dict):
        return bool(value)
    return value is not None


def _apply_packet_budget(
    *,
    packet: ChapterPacket,
    config: AppConfig,
) -> tuple[list[str], dict[str, dict[str, int]]]:
    degraded_sections: list[str] = []
    section_counts: dict[str, dict[str, int]] = {}
    section_map = {
        "broad_continuity": "previous_3_summaries",
        "fuzzy_candidates": "alias_resolution_candidates",
        "rerank_depth": "relationship_context",
        "pass3": "reveal_safe_identity_notes",
        "fallback_model": "warnings",
    }

    while True:
        total_buffered = 0
        current_sections = _token_sections(packet)
        section_counts = {}
        for section_name, section_payload in current_sections.items():
            raw = count_tokens(_canonical_json(section_payload))
            buffered = int(math.ceil(raw * 1.05))
            section_counts[section_name] = {"raw_tokens": raw, "buffered_tokens": buffered}
            total_buffered += buffered

        if total_buffered <= config.budget.max_context_per_pass:
            break

        trimmed = False
        for key in config.budget.degrade_order:
            field_name = section_map.get(key)
            if field_name is None:
                continue
            current_value = getattr(packet, field_name)
            if not _has_content(current_value):
                continue
            if field_name == "relationship_context":
                packet.relationship_context = []
                packet.chapter_safe_relationship_snippets = []
            else:
                setattr(packet, field_name, [] if not isinstance(current_value, str) else "")
            degraded_sections.append(key)
            trimmed = True
            break

        if not trimmed:
            raise RuntimeError(
                f"packet_budget_exceeded: chapter={packet.chapter_number}, buffered_tokens={total_buffered}"
            )

    return degraded_sections, section_counts


def _packet_hash(packet: ChapterPacket) -> str:
    payload = packet.to_json_dict()
    return _packet_hash_from_payload(payload)


def _packet_hash_from_payload(payload: dict[str, object]) -> str:
    normalized_payload = dict(payload)
    normalized_payload["packet_id"] = ""
    normalized_payload["built_at"] = ""
    return sha256(_canonical_json(normalized_payload).encode("utf-8")).hexdigest()


def _packet_hash_from_file(path: Path) -> str:
    payload = _read_json(path)
    payload["packet_id"] = ""
    payload["built_at"] = ""
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _record_sort_key(record: dict[str, object]) -> tuple[int, int]:
    return (
        _as_int(record.get("block_order", 0)),
        _as_int(record.get("segment_order") or 0),
    )


def build_chapter_packet(
    *,
    release_id: str,
    chapter_number: int,
    run_id: str = "packets-build",
    config: AppConfig | None = None,
    project_root: Path | None = None,
    graph_client: GraphClient | None = None,
) -> PacketBuildOutput:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    chapter_path = paths.extracted_chapters_dir / f"chapter-{chapter_number}.json"
    if not chapter_path.exists():
        raise FileNotFoundError(f"Missing extracted chapter artifact: {chapter_path}")

    chapter_payload = _read_json(chapter_path)
    records_raw = chapter_payload.get("records", [])
    if not isinstance(records_raw, list) or not records_raw:
        return PacketBuildOutput(
            status="skipped",
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            packet_id="",
            packet_hash="",
            packet_path="",
            bundle_path="",
            stale_reasons=["empty_records"],
        )
    records = [row for row in records_raw if isinstance(row, dict)]
    source_text = _collect_source_text(records)

    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    ensure_summary_schema(conn)
    ensure_idiom_schema(conn)
    ensure_graph_schema(conn)
    ensure_packet_schema(conn)

    try:
        locked_glossary = list_locked_entries(conn, release_id=release_id)
        glossary_subset = _select_glossary_subset(
            source_text=source_text,
            locked_glossary=locked_glossary,
        )
        glossary_version_hash = _hash_locked_glossary(locked_glossary)

        story_so_far = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="story_so_far_zh",
        )
        if story_so_far is None:
            conn.close()
            return PacketBuildOutput(
                status="skipped",
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                packet_id="",
                packet_hash="",
                packet_path="",
                bundle_path="",
                stale_reasons=["missing_story_so_far_summary"],
            )
        chapter_short = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_short",
        )
        if chapter_short is None:
            conn.close()
            return PacketBuildOutput(
                status="skipped",
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                packet_id="",
                packet_hash="",
                packet_path="",
                bundle_path="",
                stale_reasons=["missing_chapter_summary_short"],
            )
        previous_short = list_validated_summaries(
            conn,
            release_id=release_id,
            summary_type="chapter_summary_zh_short",
            max_chapter_number=chapter_number - 1,
        )
        previous_three = previous_short[-3:]
        active_arc = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="arc_summary_zh",
        )
        summary_rows_for_hash = [*previous_three, chapter_short, story_so_far]
        if active_arc is not None:
            summary_rows_for_hash.append(active_arc)
        summary_version_hash = _hash_summary_rows(summary_rows_for_hash)

        idiom_policies = list_policies(conn, release_id=release_id)
        idiom_subset = _select_idiom_subset(source_text=source_text, policies=idiom_policies)
        idiom_policy_hash = _hash_idiom_policies(idiom_policies)

        graph_snapshots = list_graph_snapshots(conn, release_id=release_id)
        if not graph_snapshots:
            conn.close()
            return PacketBuildOutput(
                status="skipped",
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                packet_id="",
                packet_hash="",
                packet_path="",
                bundle_path="",
                stale_reasons=["missing_graph_snapshot"],
            )
        latest_snapshot = graph_snapshots[-1]

        chapter_source_hash = str(chapter_payload.get("chapter_source_hash", "")).strip()
        if not chapter_source_hash:
            raise RuntimeError(
                f"missing_chapter_source_hash: release={release_id}, chapter={chapter_number}"
            )

        latest_metadata = get_latest_packet_metadata(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
        )
        staleness = detect_stale_packet(
            latest_metadata,
            chapter_source_hash=chapter_source_hash,
            glossary_version_hash=glossary_version_hash,
            summary_version_hash=summary_version_hash,
            graph_snapshot_hash=latest_snapshot.snapshot_hash,
            idiom_policy_hash=idiom_policy_hash,
        )

        if latest_metadata is not None and not staleness.is_stale:
            packet_path_ref = Path(latest_metadata.packet_path)
            bundle_path_ref = Path(latest_metadata.bundle_path)
            if packet_path_ref.exists() and bundle_path_ref.exists():
                return PacketBuildOutput(
                    status="up_to_date",
                    release_id=release_id,
                    run_id=run_id,
                    chapter_number=chapter_number,
                    packet_id=latest_metadata.packet_id,
                    packet_hash=latest_metadata.packet_hash,
                    packet_path=latest_metadata.packet_path,
                    bundle_path=latest_metadata.bundle_path,
                    stale_reasons=[],
                )
            staleness.reasons.append("missing_packet_artifact")
            staleness.is_stale = True

        graph = _build_graph_client(paths, graph_client)
        graph_context = enrich_with_graph_context(
            chapter_number=chapter_number,
            source_text=source_text,
            glossary_subset=glossary_subset,
            graph_client=graph,
        )

        chapter_metadata = {
            "chapter_id": chapter_payload.get("chapter_id"),
            "source_document_path": chapter_payload.get("source_document_path"),
            "record_count": len(records),
            "block_count": len({str(row.get("parent_block_id", "")) for row in records}),
        }
        built_at = datetime.now(UTC).isoformat()
        packet = ChapterPacket(
            packet_id="",
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            chapter_metadata=chapter_metadata,
            chapter_glossary_subset=[row.to_json_dict() for row in glossary_subset],
            previous_3_summaries=[
                {
                    "summary_id": row.summary_id,
                    "chapter_number": row.chapter_number,
                    "content_zh": row.content_zh,
                }
                for row in previous_three
            ],
            story_so_far_summary=story_so_far.content_zh,
            chapter_summary_short=chapter_short.content_zh,
            active_arc_summary=None if active_arc is None else active_arc.content_zh,
            chapter_local_idioms=[row.to_json_dict() for row in idiom_subset],
            graph_snapshot_reference=latest_snapshot.to_json_dict(),
            entity_context=graph_context["entity_context"],
            relationship_context=graph_context["relationship_context"],
            chapter_safe_relationship_snippets=graph_context["chapter_safe_relationship_snippets"],
            alias_resolution_candidates=graph_context["alias_resolution_candidates"],
            reveal_safe_identity_notes=graph_context["reveal_safe_identity_notes"],
            warnings=[],
            trimmed_sections=[],
            section_token_counts={},
            packet_schema_version=PACKET_SCHEMA_VERSION,
            chapter_source_hash=chapter_source_hash,
            glossary_version_hash=glossary_version_hash,
            summary_version_hash=summary_version_hash,
            graph_snapshot_hash=latest_snapshot.snapshot_hash,
            idiom_policy_hash=idiom_policy_hash,
            packet_builder_version=PACKET_BUILDER_VERSION,
            built_at=built_at,
        )
        trimmed_sections, section_token_counts = _apply_packet_budget(packet=packet, config=config_obj)
        packet.trimmed_sections = trimmed_sections
        packet.section_token_counts = section_token_counts
        if trimmed_sections:
            packet.warnings = [f"trimmed:{key}" for key in trimmed_sections]

        packet_hash = _packet_hash(packet)
        packet.packet_id = f"pkt_{packet_hash[:24]}"

        packet_path = paths.packets_dir / f"chapter-{chapter_number}-{packet.packet_id}.json"
        bundle_path = paths.packets_dir / f"chapter-{chapter_number}-{packet.packet_id}-bundles.json"

        bundles: list[ParagraphBundle] = []
        bundle_warnings: list[str] = []
        for row in sorted(records, key=_record_sort_key):
            try:
                bundle = build_paragraph_bundle(
                    packet=packet,
                    block_record=row,
                    max_bundle_bytes=config_obj.budget.max_bundle_bytes,
                )
                bundles.append(bundle)
            except RuntimeError as exc:
                bundle_warnings.append(f"bundle_skip: block={row.get('block_id', '?')}: {exc}")
        if bundle_warnings:
            packet.warnings.extend(bundle_warnings)

        packet_payload = packet.to_json_dict()
        bundle_payload = {
            "release_id": release_id,
            "run_id": run_id,
            "chapter_number": chapter_number,
            "packet_id": packet.packet_id,
            "packet_hash": packet_hash,
            "schema_version": 1,
            "bundles": [row.to_json_dict() for row in bundles],
        }
        _write_json(packet_path, packet_payload)
        _write_json(bundle_path, bundle_payload)

        persisted_packet_hash = _packet_hash_from_file(packet_path)
        if persisted_packet_hash != packet_hash:
            raise RuntimeError(
                f"packet_hash_mismatch: expected={packet_hash}, actual={persisted_packet_hash}"
            )

        metadata = PacketMetadataRecord(
            packet_id=packet.packet_id,
            release_id=release_id,
            chapter_number=chapter_number,
            run_id=run_id,
            packet_path=str(packet_path),
            bundle_path=str(bundle_path),
            packet_hash=packet_hash,
            chapter_source_hash=chapter_source_hash,
            glossary_version_hash=glossary_version_hash,
            summary_version_hash=summary_version_hash,
            graph_snapshot_hash=latest_snapshot.snapshot_hash,
            idiom_policy_hash=idiom_policy_hash,
            packet_builder_version=PACKET_BUILDER_VERSION,
            packet_schema_version=PACKET_SCHEMA_VERSION,
        )
        save_packet_metadata(conn, metadata=metadata)
    finally:
        conn.close()

    return PacketBuildOutput(
        status="rebuilt_stale" if staleness.is_stale else "built",
        release_id=release_id,
        run_id=run_id,
        chapter_number=chapter_number,
        packet_id=packet.packet_id,
        packet_hash=packet_hash,
        packet_path=str(packet_path),
        bundle_path=str(bundle_path),
        stale_reasons=staleness.reasons,
    )


def build_packets(
    *,
    release_id: str,
    run_id: str = "packets-build",
    chapter_number: int | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    graph_client: GraphClient | None = None,
) -> dict[str, object]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    if chapter_number is not None:
        targets = [chapter_number]
    else:
        chapter_files = sorted(
            paths.extracted_chapters_dir.glob("chapter-*.json"),
            key=_chapter_number_from_path,
        )
        targets = [_chapter_number_from_path(path) for path in chapter_files]

    if chapter_start is not None:
        targets = [n for n in targets if n >= chapter_start]
    if chapter_end is not None:
        targets = [n for n in targets if n <= chapter_end]

    if not targets:
        raise FileNotFoundError(
            f"No extracted chapters found for release {release_id}: {paths.extracted_chapters_dir}"
        )

    results: list[PacketBuildOutput] = []
    failures: list[str] = []
    for number in targets:
        try:
            result = build_chapter_packet(
                release_id=release_id,
                chapter_number=number,
                run_id=run_id,
                config=config_obj,
                project_root=project_root,
                graph_client=graph_client,
            )
            results.append(result)
        except Exception as exc:
            failures.append(f"ch{number}: {exc}")
            results.append(PacketBuildOutput(
                status="failed",
                release_id=release_id,
                run_id=run_id,
                chapter_number=number,
                packet_id="",
                packet_hash="",
                packet_path="",
                bundle_path="",
                stale_reasons=[str(exc)],
            ))
    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "chapters_requested": len(targets),
        "chapters_built": len([row for row in results if row.status == "rebuilt_stale" or row.status == "built"]),
        "chapters_up_to_date": len([row for row in results if row.status == "up_to_date"]),
        "chapters_skipped": len([row for row in results if row.status == "skipped"]),
        "chapters_failed": len([row for row in results if row.status == "failed"]),
        "results": [row.to_json_dict() for row in results],
    }
