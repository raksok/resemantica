from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from resemantica.db.glossary_repo import ensure_glossary_schema, promote_locked_entries
from resemantica.db.graph_repo import ensure_graph_schema, list_deferred_entities, list_graph_snapshots
from resemantica.db.sqlite import open_connection
from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.glossary.validators import normalize_term
from resemantica.graph.client import GraphClient, InMemoryGraphBackend
from resemantica.graph.filters import filter_for_chapter
from resemantica.graph.models import GraphAlias, GraphAppearance, GraphEntity, GraphRelationship
from resemantica.graph.pipeline import preprocess_graph
from resemantica.graph.validators import validate_graph_state
from resemantica.settings import derive_paths, load_config


def _write_extracted_chapter(
    *,
    release_id: str,
    chapter_number: int,
    source_text: str,
) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)

    block_id = f"ch{chapter_number:03d}_blk001"
    payload = {
        "chapter_id": f"chapter-{chapter_number}",
        "chapter_number": chapter_number,
        "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
        "chapter_source_hash": f"hash-{chapter_number}",
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
                "chapter_source_hash": f"hash-{chapter_number}",
                "schema_version": 1,
            }
        ],
    }
    chapter_path = paths.extracted_chapters_dir / f"chapter-{chapter_number}.json"
    chapter_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _insert_locked_glossary_entry(
    *,
    release_id: str,
    source_term: str,
    target_term: str,
    category: str,
) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        promote_locked_entries(
            conn,
            entries=[
                LockedGlossaryEntry(
                    glossary_entry_id=f"glex_{category}_{normalize_term(source_term)}",
                    release_id=release_id,
                    source_term=source_term,
                    normalized_source_term=normalize_term(source_term),
                    target_term=target_term,
                    normalized_target_term=normalize_term(target_term),
                    category=category,
                    status="approved",
                    approved_at=datetime.now(UTC).isoformat(),
                    approval_run_id="promote-test",
                    source_candidate_id=f"gcan_{category}_{normalize_term(source_term)}",
                    schema_version=1,
                )
            ],
        )
    finally:
        conn.close()


def test_alias_reveal_gating() -> None:
    entity = GraphEntity(
        entity_id="ent_1",
        release_id="rel",
        entity_type="character",
        canonical_name="Zhang San",
        glossary_entry_id="glex_1",
        first_seen_chapter=1,
        last_seen_chapter=10,
        revealed_chapter=1,
        status="confirmed",
        schema_version=1,
    )
    alias = GraphAlias(
        alias_id="alias_1",
        release_id="rel",
        entity_id="ent_1",
        alias_text="Masked Hero",
        alias_language="zh",
        first_seen_chapter=1,
        last_seen_chapter=10,
        revealed_chapter=3,
        confidence=0.9,
        is_masked_identity=True,
        status="confirmed",
        schema_version=1,
    )

    chapter_2 = filter_for_chapter(
        entities=[entity],
        aliases=[alias],
        appearances=[],
        relationships=[],
        chapter_number=2,
    )
    chapter_3 = filter_for_chapter(
        entities=[entity],
        aliases=[alias],
        appearances=[],
        relationships=[],
        chapter_number=3,
    )

    assert chapter_2.aliases == []
    assert [row.alias_id for row in chapter_3.aliases] == ["alias_1"]


def test_chapter_safe_relationship_filter() -> None:
    entities = [
        GraphEntity(
            entity_id="ent_a",
            release_id="rel",
            entity_type="character",
            canonical_name="A",
            glossary_entry_id="glex_a",
            first_seen_chapter=1,
            last_seen_chapter=10,
            revealed_chapter=1,
            status="confirmed",
            schema_version=1,
        ),
        GraphEntity(
            entity_id="ent_b",
            release_id="rel",
            entity_type="character",
            canonical_name="B",
            glossary_entry_id="glex_b",
            first_seen_chapter=1,
            last_seen_chapter=10,
            revealed_chapter=1,
            status="confirmed",
            schema_version=1,
        ),
    ]
    relationships = [
        GraphRelationship(
            relationship_id="rel_ok",
            release_id="rel",
            type="teacher_of",
            source_entity_id="ent_a",
            target_entity_id="ent_b",
            source_chapter=1,
            start_chapter=1,
            end_chapter=None,
            revealed_chapter=1,
            confidence=0.8,
            status="confirmed",
            schema_version=1,
        ),
        GraphRelationship(
            relationship_id="rel_future",
            release_id="rel",
            type="teacher_of",
            source_entity_id="ent_a",
            target_entity_id="ent_b",
            source_chapter=1,
            start_chapter=1,
            end_chapter=None,
            revealed_chapter=5,
            confidence=0.8,
            status="confirmed",
            schema_version=1,
        ),
        GraphRelationship(
            relationship_id="rel_expired",
            release_id="rel",
            type="teacher_of",
            source_entity_id="ent_a",
            target_entity_id="ent_b",
            source_chapter=1,
            start_chapter=1,
            end_chapter=1,
            revealed_chapter=1,
            confidence=0.8,
            status="confirmed",
            schema_version=1,
        ),
    ]

    chapter_2 = filter_for_chapter(
        entities=entities,
        aliases=[],
        appearances=[],
        relationships=relationships,
        chapter_number=2,
    )
    assert [row.relationship_id for row in chapter_2.relationships] == ["rel_ok"]


def test_graph_validator_rejects_invalid_references_and_ranges() -> None:
    validation = validate_graph_state(
        entities=[
            GraphEntity(
                entity_id="ent_1",
                release_id="rel",
                entity_type="character",
                canonical_name="A",
                glossary_entry_id="glex_1",
                first_seen_chapter=3,
                last_seen_chapter=1,
                revealed_chapter=1,
                status="confirmed",
                schema_version=1,
            )
        ],
        aliases=[],
        appearances=[
            GraphAppearance(
                appearance_id="app_1",
                release_id="rel",
                entity_id="missing",
                chapter_number=1,
                evidence_snippet="x",
                status="confirmed",
                schema_version=1,
            )
        ],
        relationships=[
            GraphRelationship(
                relationship_id="rel_1",
                release_id="rel",
                type="ally_of",
                source_entity_id="ent_1",
                target_entity_id="missing",
                source_chapter=5,
                start_chapter=2,
                end_chapter=1,
                revealed_chapter=1,
                confidence=0.7,
                status="confirmed",
                schema_version=1,
            )
        ],
    )

    assert not validation.is_valid
    assert any("dangling_reference" in err for err in validation.errors)
    assert any("chapter_range_invalid" in err for err in validation.errors)


def test_deferred_entity_lifecycle_and_confirmed_state_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m6-deferred"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="苍云门，势力扩张。",
    )

    backend = InMemoryGraphBackend()
    client = GraphClient(backend=backend)

    first = preprocess_graph(
        release_id=release_id,
        run_id="graph-001",
        graph_client=client,
    )
    assert first["status"] == "success"
    assert first["deferred_pending_count"] >= 1

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_graph_schema(conn)
    try:
        pending = list_deferred_entities(
            conn,
            release_id=release_id,
            status="pending_glossary",
        )
        assert pending
        assert pending[0].term_text == "苍云门"
    finally:
        conn.close()

    _insert_locked_glossary_entry(
        release_id=release_id,
        source_term="苍云门",
        target_term="Azure Cloud Sect",
        category="faction",
    )

    second = preprocess_graph(
        release_id=release_id,
        run_id="graph-002",
        graph_client=client,
    )
    assert second["status"] == "success"
    assert second["deferred_graph_created_count"] >= 1

    conn = open_connection(paths.db_path)
    ensure_graph_schema(conn)
    try:
        created = list_deferred_entities(
            conn,
            release_id=release_id,
            status="graph_created",
        )
        assert created
        assert created[0].glossary_entry_id is not None
    finally:
        conn.close()

    confirmed_entities = client.list_entities(status="confirmed")
    assert confirmed_entities
    assert all(row.status == "confirmed" for row in client.list_entities())
    assert all(row.glossary_entry_id for row in confirmed_entities)


def test_snapshot_metadata_written_for_packet_reproducibility(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m6-snapshot"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="青云门今日议事。",
    )
    _insert_locked_glossary_entry(
        release_id=release_id,
        source_term="青云门",
        target_term="Azure Sect",
        category="faction",
    )

    result = preprocess_graph(
        release_id=release_id,
        run_id="graph-001",
        graph_client=GraphClient(backend=InMemoryGraphBackend()),
    )
    assert result["status"] == "success"
    assert len(result["snapshot_hash"]) == 64

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    snapshot_payload = json.loads(paths.graph_snapshot_path.read_text(encoding="utf-8"))
    assert snapshot_payload["snapshot"]["snapshot_hash"] == result["snapshot_hash"]
    assert snapshot_payload["snapshot"]["entity_count"] >= 1

    conn = open_connection(paths.db_path)
    ensure_graph_schema(conn)
    try:
        snapshots = list_graph_snapshots(conn, release_id=release_id)
        assert len(snapshots) == 1
        assert snapshots[0].snapshot_hash == result["snapshot_hash"]
    finally:
        conn.close()
