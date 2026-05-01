from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from resemantica.db.glossary_repo import ensure_glossary_schema, promote_locked_entries
from resemantica.db.graph_repo import ensure_graph_schema, save_graph_snapshot
from resemantica.db.idiom_repo import ensure_idiom_schema, promote_policies
from resemantica.db.sqlite import open_connection
from resemantica.db.summary_repo import ensure_summary_schema, save_validated_summary
from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.glossary.validators import normalize_term
from resemantica.graph.client import GraphClient, InMemoryGraphBackend
from resemantica.graph.models import GraphAlias, GraphAppearance, GraphEntity, GraphRelationship
from resemantica.idioms.models import IdiomPolicy
from resemantica.idioms.validators import normalize_idiom_source
from resemantica.packets.builder import build_chapter_packet
from resemantica.packets.invalidation import detect_stale_packet
from resemantica.settings import derive_paths, load_config


@pytest.fixture(autouse=True)
def _mock_token_counter(monkeypatch) -> None:
    def fake_count_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 8)

    monkeypatch.setattr("resemantica.packets.builder.count_tokens", fake_count_tokens)
    monkeypatch.setattr("resemantica.packets.bundler.count_tokens", fake_count_tokens)


def _write_extracted_chapter(
    *,
    release_id: str,
    chapter_number: int,
    source_text: str,
    chapter_source_hash: str,
) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
    block_id = f"ch{chapter_number:03d}_blk001"
    payload = {
        "chapter_id": f"chapter-{chapter_number}",
        "chapter_number": chapter_number,
        "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
        "chapter_source_hash": chapter_source_hash,
        "schema_version": 1,
        "records": [
            {
                "chapter_id": f"chapter-{chapter_number}",
                "chapter_number": chapter_number,
                "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
                "block_id": block_id,
                "parent_block_id": block_id,
                "segment_id": None,
                "block_order": 1,
                "segment_order": None,
                "source_text_zh": source_text,
                "placeholder_map_ref": "",
                "chapter_source_hash": chapter_source_hash,
                "schema_version": 1,
            }
        ],
    }
    (paths.extracted_chapters_dir / f"chapter-{chapter_number}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _seed_glossary(
    *,
    release_id: str,
    rows: list[tuple[str, str, str]],
) -> dict[str, str]:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    mapping: dict[str, str] = {}
    try:
        entries: list[LockedGlossaryEntry] = []
        for source_term, target_term, category in rows:
            entry_id = f"glex_{category}_{normalize_term(source_term)}"
            mapping[source_term] = entry_id
            entries.append(
                LockedGlossaryEntry(
                    glossary_entry_id=entry_id,
                    release_id=release_id,
                    source_term=source_term,
                    normalized_source_term=normalize_term(source_term),
                    target_term=target_term,
                    normalized_target_term=normalize_term(target_term),
                    category=category,
                    status="approved",
                    approved_at=datetime.now(UTC).isoformat(),
                    approval_run_id="seed-glossary",
                    source_candidate_id=f"gcan_{category}_{normalize_term(source_term)}",
                    schema_version=1,
                )
            )
        promote_locked_entries(conn, entries=entries)
    finally:
        conn.close()
    return mapping


def _seed_summaries(
    *,
    release_id: str,
    chapter_number: int,
    chapter_hash: str,
    chapter_short: str,
    story_so_far: str,
) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        save_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_short",
            content_zh=chapter_short,
            derived_from_chapter_hash=chapter_hash,
            run_id="seed-summaries",
            validation_status="approved",
        )
        save_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="story_so_far_zh",
            content_zh=story_so_far,
            derived_from_chapter_hash=chapter_hash,
            run_id="seed-summaries",
            validation_status="approved",
        )
    finally:
        conn.close()


def _seed_idioms(*, release_id: str, rows: list[tuple[str, str, str]]) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        policies = [
            IdiomPolicy(
                idiom_id=f"idi_{normalize_idiom_source(source_text)}",
                release_id=release_id,
                source_text=source_text,
                normalized_source_text=normalize_idiom_source(source_text),
                meaning_zh=meaning_zh,
                preferred_rendering_en=rendering_en,
                usage_notes=None,
                policy_status="approved",
                first_seen_chapter=1,
                last_seen_chapter=1,
                appearance_count=1,
                promoted_from_candidate_id=f"ican_{normalize_idiom_source(source_text)}",
                approval_run_id="seed-idioms",
                schema_version=1,
            )
            for source_text, meaning_zh, rendering_en in rows
        ]
        promote_policies(conn, policies=policies)
    finally:
        conn.close()


def _seed_graph(
    *,
    release_id: str,
    graph_client: GraphClient,
    glossary_ids: dict[str, str],
    include_non_local_edge: bool = False,
) -> None:
    entity_zhang = GraphEntity(
        entity_id="ent_zhang",
        release_id=release_id,
        entity_type="character",
        canonical_name="Zhang San",
        glossary_entry_id=glossary_ids["张三"],
        first_seen_chapter=1,
        last_seen_chapter=20,
        revealed_chapter=1,
        status="confirmed",
        schema_version=1,
    )
    entity_sect = GraphEntity(
        entity_id="ent_sect",
        release_id=release_id,
        entity_type="faction",
        canonical_name="Azure Sect",
        glossary_entry_id=glossary_ids["青云门"],
        first_seen_chapter=1,
        last_seen_chapter=20,
        revealed_chapter=1,
        status="confirmed",
        schema_version=1,
    )
    entity_other = GraphEntity(
        entity_id="ent_other",
        release_id=release_id,
        entity_type="character",
        canonical_name="Li Si",
        glossary_entry_id=glossary_ids.get("李四"),
        first_seen_chapter=1,
        last_seen_chapter=20,
        revealed_chapter=1,
        status="confirmed",
        schema_version=1,
    )

    graph_client.upsert_entities(entities=[entity_zhang, entity_sect, entity_other])
    graph_client.upsert_aliases(
        aliases=[
            GraphAlias(
                alias_id="alias_conflict",
                release_id=release_id,
                entity_id="ent_other",
                alias_text="青云门",
                alias_language="zh",
                first_seen_chapter=1,
                last_seen_chapter=20,
                revealed_chapter=1,
                confidence=0.8,
                is_masked_identity=False,
                status="confirmed",
                schema_version=1,
            )
        ]
    )
    graph_client.upsert_appearances(
        appearances=[
            GraphAppearance(
                appearance_id="app_zhang_ch1",
                release_id=release_id,
                entity_id="ent_zhang",
                chapter_number=1,
                evidence_snippet="张三出场",
                status="confirmed",
                schema_version=1,
            )
        ]
    )
    relationships = [
        GraphRelationship(
            relationship_id="rel_local",
            release_id=release_id,
            type="MEMBER_OF",
            source_entity_id="ent_zhang",
            target_entity_id="ent_sect",
            source_chapter=1,
            start_chapter=1,
            end_chapter=None,
            revealed_chapter=1,
            confidence=0.9,
            status="confirmed",
            lore_text="张三正式入门。",
            is_masked_identity=False,
            schema_version=1,
        )
    ]
    if include_non_local_edge:
        relationships.append(
            GraphRelationship(
                relationship_id="rel_non_local",
                release_id=release_id,
                type="MEMBER_OF",
                source_entity_id="ent_zhang",
                target_entity_id="ent_other",
                source_chapter=1,
                start_chapter=1,
                end_chapter=None,
                revealed_chapter=1,
                confidence=0.7,
                status="confirmed",
                lore_text=None,
                is_masked_identity=False,
                schema_version=1,
            )
        )
    graph_client.upsert_relationships(relationships=relationships)

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    snapshot = graph_client.export_snapshot(
        release_id=release_id,
        graph_db_path=paths.graph_db_path,
    )
    conn = open_connection(paths.db_path)
    ensure_graph_schema(conn)
    try:
        save_graph_snapshot(conn, snapshot=snapshot)
    finally:
        conn.close()


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Invalid JSON payload")
    return payload


def test_packet_schema_and_provenance_hashes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m8-schema"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三加入青云门，可谓一箭双雕。",
        chapter_source_hash="hash-ch1",
    )
    glossary_ids = _seed_glossary(
        release_id=release_id,
        rows=[
            ("张三", "Zhang San", "character"),
            ("青云门", "Azure Sect", "faction"),
            ("李四", "Li Si", "character"),
        ],
    )
    _seed_summaries(
        release_id=release_id,
        chapter_number=1,
        chapter_hash="hash-ch1",
        chapter_short="张三入门。",
        story_so_far="第1章：张三入门。",
    )
    _seed_idioms(
        release_id=release_id,
        rows=[("一箭双雕", "一举两得", "kill two birds with one stone")],
    )

    graph_client = GraphClient(backend=InMemoryGraphBackend())
    _seed_graph(
        release_id=release_id,
        graph_client=graph_client,
        glossary_ids=glossary_ids,
    )

    result = build_chapter_packet(
        release_id=release_id,
        chapter_number=1,
        run_id="packets-001",
        graph_client=graph_client,
    )
    assert result.status in {"built", "rebuilt_stale"}

    packet_payload = _read_json(Path(result.packet_path))
    for key in (
        "chapter_source_hash",
        "glossary_version_hash",
        "summary_version_hash",
        "graph_snapshot_hash",
        "idiom_policy_hash",
        "packet_builder_version",
    ):
        assert key in packet_payload
    assert int(packet_payload["packet_schema_version"]) == 1
    assert len(str(packet_payload["chapter_source_hash"])) > 0
    assert len(str(packet_payload["glossary_version_hash"])) == 64
    assert len(str(packet_payload["summary_version_hash"])) == 64
    assert len(str(packet_payload["graph_snapshot_hash"])) == 64
    assert len(str(packet_payload["idiom_policy_hash"])) == 64

    bundles_payload = _read_json(Path(result.bundle_path))
    bundles = list(bundles_payload["bundles"])
    assert bundles


def test_stale_detection_triggers_packet_rebuild(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m8-stale"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三进入青云门。",
        chapter_source_hash="hash-ch1",
    )
    glossary_ids = _seed_glossary(
        release_id=release_id,
        rows=[("张三", "Zhang San", "character"), ("青云门", "Azure Sect", "faction"), ("李四", "Li Si", "character")],
    )
    _seed_summaries(
        release_id=release_id,
        chapter_number=1,
        chapter_hash="hash-ch1",
        chapter_short="张三入门。",
        story_so_far="第1章：张三入门。",
    )
    _seed_idioms(release_id=release_id, rows=[])
    graph_client = GraphClient(backend=InMemoryGraphBackend())
    _seed_graph(
        release_id=release_id,
        graph_client=graph_client,
        glossary_ids=glossary_ids,
    )

    first = build_chapter_packet(
        release_id=release_id,
        chapter_number=1,
        run_id="packets-001",
        graph_client=graph_client,
    )
    assert first.status in {"built", "rebuilt_stale"}

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    from resemantica.db.packet_repo import ensure_packet_schema, get_latest_packet_metadata

    ensure_packet_schema(conn)
    metadata = get_latest_packet_metadata(conn, release_id=release_id, chapter_number=1)
    conn.close()
    assert metadata is not None

    stale = detect_stale_packet(
        metadata,
        chapter_source_hash=metadata.chapter_source_hash,
        glossary_version_hash=metadata.glossary_version_hash,
        summary_version_hash="changed-summary-hash",
        graph_snapshot_hash=metadata.graph_snapshot_hash,
        idiom_policy_hash=metadata.idiom_policy_hash,
    )
    assert stale.is_stale
    assert "summary_version_hash_changed" in stale.reasons

    _seed_summaries(
        release_id=release_id,
        chapter_number=1,
        chapter_hash="hash-ch1",
        chapter_short="张三正式入门。",
        story_so_far="第1章：张三正式入门。",
    )
    second = build_chapter_packet(
        release_id=release_id,
        chapter_number=1,
        run_id="packets-002",
        graph_client=graph_client,
    )
    assert second.status == "rebuilt_stale"
    assert "summary_version_hash_changed" in second.stale_reasons
    assert second.packet_hash != first.packet_hash


def test_graph_to_packet_filtering_is_local_and_chapter_safe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m8-graph-filter"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三来到青云门。",
        chapter_source_hash="hash-ch1",
    )
    glossary_ids = _seed_glossary(
        release_id=release_id,
        rows=[("张三", "Zhang San", "character"), ("青云门", "Azure Sect", "faction"), ("李四", "Li Si", "character")],
    )
    _seed_summaries(
        release_id=release_id,
        chapter_number=1,
        chapter_hash="hash-ch1",
        chapter_short="张三来到宗门。",
        story_so_far="第1章：张三来到宗门。",
    )
    _seed_idioms(release_id=release_id, rows=[])
    graph_client = GraphClient(backend=InMemoryGraphBackend())
    _seed_graph(
        release_id=release_id,
        graph_client=graph_client,
        glossary_ids=glossary_ids,
        include_non_local_edge=True,
    )

    result = build_chapter_packet(
        release_id=release_id,
        chapter_number=1,
        run_id="packets-001",
        graph_client=graph_client,
    )
    packet_payload = _read_json(Path(result.packet_path))
    relationship_ids = {
        str(row.get("relationship_id"))
        for row in list(packet_payload["relationship_context"])
    }
    assert "rel_local" in relationship_ids
    assert "rel_non_local" not in relationship_ids


def test_packet_size_budget_trims_lower_priority_sections(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m8-budget"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三加入青云门。",
        chapter_source_hash="hash-ch1",
    )
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=2,
        source_text="张三在青云门经历了漫长的试炼并结识同门。",
        chapter_source_hash="hash-ch2",
    )
    glossary_ids = _seed_glossary(
        release_id=release_id,
        rows=[("张三", "Zhang San", "character"), ("青云门", "Azure Sect", "faction"), ("李四", "Li Si", "character")],
    )
    _seed_summaries(
        release_id=release_id,
        chapter_number=1,
        chapter_hash="hash-ch1",
        chapter_short="张三入门并开始修炼，这一段非常漫长。" * 4,
        story_so_far="第1章：张三入门并开始修炼。" * 4,
    )
    _seed_summaries(
        release_id=release_id,
        chapter_number=2,
        chapter_hash="hash-ch2",
        chapter_short="张三经历多轮试炼并逐步成长。" * 4,
        story_so_far="第1章：张三入门。\n第2章：张三经历多轮试炼并逐步成长。" * 4,
    )
    _seed_idioms(release_id=release_id, rows=[])
    graph_client = GraphClient(backend=InMemoryGraphBackend())
    _seed_graph(
        release_id=release_id,
        graph_client=graph_client,
        glossary_ids=glossary_ids,
    )

    config = load_config()
    config.budget.max_context_per_pass = 190
    result = build_chapter_packet(
        release_id=release_id,
        chapter_number=2,
        run_id="packets-001",
        config=config,
        graph_client=graph_client,
    )
    packet_payload = _read_json(Path(result.packet_path))
    trimmed = list(packet_payload["trimmed_sections"])
    assert trimmed
    buffered_total = sum(
        int(row["buffered_tokens"])
        for row in dict(packet_payload["section_token_counts"]).values()
    )
    assert buffered_total <= config.budget.max_context_per_pass


def test_retrieval_precedence_glossary_beats_graph_alias(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m8-precedence"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三加入青云门。",
        chapter_source_hash="hash-ch1",
    )
    glossary_ids = _seed_glossary(
        release_id=release_id,
        rows=[("张三", "Zhang San", "character"), ("青云门", "Azure Sect", "faction"), ("李四", "Li Si", "character")],
    )
    _seed_summaries(
        release_id=release_id,
        chapter_number=1,
        chapter_hash="hash-ch1",
        chapter_short="张三入门。",
        story_so_far="第1章：张三入门。",
    )
    _seed_idioms(
        release_id=release_id,
        rows=[("一箭双雕", "一举两得", "kill two birds with one stone")],
    )
    graph_client = GraphClient(backend=InMemoryGraphBackend())
    _seed_graph(
        release_id=release_id,
        graph_client=graph_client,
        glossary_ids=glossary_ids,
    )

    result = build_chapter_packet(
        release_id=release_id,
        chapter_number=1,
        run_id="packets-001",
        graph_client=graph_client,
    )
    bundles_payload = _read_json(Path(result.bundle_path))
    bundles = list(bundles_payload["bundles"])
    assert len(bundles) == 1
    bundle = dict(bundles[0])
    glossary_terms = {
        str(row.get("source_term"))
        for row in list(bundle["matched_glossary_entries"])
    }
    alias_terms = {
        str(row.get("alias_text"))
        for row in list(bundle["alias_resolutions"])
    }
    assert "青云门" in glossary_terms
    assert "青云门" not in alias_terms
    evidence = "\n".join(str(row) for row in list(bundle["retrieval_evidence_summary"]))
    assert "graph_alias:0" in evidence
