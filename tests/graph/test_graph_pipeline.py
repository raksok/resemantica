from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re

from resemantica.db.glossary_repo import ensure_glossary_schema, promote_locked_entries
from resemantica.db.graph_repo import ensure_graph_schema, list_deferred_entities, list_graph_snapshots
from resemantica.db.sqlite import open_connection
from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.glossary.validators import normalize_term
from resemantica.graph.client import GraphClient, InMemoryGraphBackend
from resemantica.graph.filters import (
    filter_for_chapter,
    get_hierarchy_context,
    get_revealed_lore,
    select_local_world_model_edges,
)
from resemantica.graph.models import (
    GraphAlias,
    GraphAppearance,
    GraphEntity,
    GraphRelationship,
)
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


class ScriptedGraphLLM:
    def __init__(
        self,
        entities_by_chapter: dict[int, list[dict]],
        relationships_by_chapter: dict[int, list[dict]] | None = None,
    ) -> None:
        self.entities_by_chapter = entities_by_chapter
        self.relationships_by_chapter = relationships_by_chapter or {}

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        chapter_match = re.search(r"## CHAPTER NUMBER\s+(\d+)", prompt)
        if chapter_match is None:
            return '{"entities": [], "relationships": []}'
        chapter_number = int(chapter_match.group(1))
        return json.dumps(
            {
                "entities": self.entities_by_chapter.get(chapter_number, []),
                "relationships": self.relationships_by_chapter.get(chapter_number, []),
            },
            ensure_ascii=False,
        )


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

    mock_llm = ScriptedGraphLLM({
        1: [
            {"source_term": "苍云门", "entity_type": "faction", "aliases": [], "evidence_snippet": "苍云门，势力扩张。"},
        ],
    })

    backend = InMemoryGraphBackend()
    client = GraphClient(backend=backend)

    first = preprocess_graph(
        release_id=release_id,
        run_id="graph-001",
        graph_client=client,
        llm_client=mock_llm,
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
        llm_client=mock_llm,
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

    mock_llm = ScriptedGraphLLM({
        1: [
            {"source_term": "青云门", "entity_type": "faction", "aliases": [], "evidence_snippet": "青云门今日议事。"},
        ],
    })

    result = preprocess_graph(
        release_id=release_id,
        run_id="graph-001",
        graph_client=GraphClient(backend=InMemoryGraphBackend()),
        llm_client=mock_llm,
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


def test_role_state_transition_across_chapters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m7-role-state"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三成为外门弟子。",
    )
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=2,
        source_text="张三晋升长老。",
    )

    _insert_locked_glossary_entry(
        release_id=release_id,
        source_term="张三",
        target_term="Zhang San",
        category="character",
    )
    _insert_locked_glossary_entry(
        release_id=release_id,
        source_term="外门弟子",
        target_term="Outer Disciple",
        category="generic_role",
    )
    _insert_locked_glossary_entry(
        release_id=release_id,
        source_term="长老",
        target_term="Elder",
        category="title_honorific",
    )

    mock_llm = ScriptedGraphLLM(
        entities_by_chapter={
            1: [
                {"source_term": "张三", "entity_type": "character", "aliases": [], "evidence_snippet": "张三成为外门弟子。"},
                {"source_term": "外门弟子", "entity_type": "generic_role", "aliases": [], "evidence_snippet": "张三成为外门弟子。"},
            ],
            2: [
                {"source_term": "张三", "entity_type": "character", "aliases": [], "evidence_snippet": "张三晋升长老。"},
                {"source_term": "长老", "entity_type": "title_honorific", "aliases": [], "evidence_snippet": "张三晋升长老。"},
            ],
        },
        relationships_by_chapter={
            1: [
                {"type": "RANKED_AS", "source_term": "张三", "target_term": "外门弟子", "evidence_snippet": "张三成为外门弟子。", "confidence": 0.9, "lore_text": None, "is_masked_identity": False},
            ],
            2: [
                {"type": "RANKED_AS", "source_term": "张三", "target_term": "长老", "evidence_snippet": "张三晋升长老。", "confidence": 0.9, "lore_text": None, "is_masked_identity": False},
            ],
        },
    )

    client = GraphClient(backend=InMemoryGraphBackend())
    result = preprocess_graph(
        release_id=release_id,
        run_id="graph-001",
        graph_client=client,
        llm_client=mock_llm,
    )
    assert result["status"] == "success"

    ranked = [
        row
        for row in client.list_relationships(status="confirmed")
        if row.type == "RANKED_AS"
    ]
    assert len(ranked) == 2
    ranked_sorted = sorted(ranked, key=lambda row: row.start_chapter)
    assert ranked_sorted[0].start_chapter == 1
    assert ranked_sorted[0].end_chapter == 1
    assert ranked_sorted[1].start_chapter == 2
    assert ranked_sorted[1].end_chapter is None


def test_containment_visibility_by_chapter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m7-containment"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="张三在青云山修炼。",
    )
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=2,
        source_text="张三来到天云城。",
    )

    _insert_locked_glossary_entry(
        release_id=release_id,
        source_term="张三",
        target_term="Zhang San",
        category="character",
    )
    _insert_locked_glossary_entry(
        release_id=release_id,
        source_term="青云山",
        target_term="Azure Mountain",
        category="location",
    )
    _insert_locked_glossary_entry(
        release_id=release_id,
        source_term="天云城",
        target_term="Skycloud City",
        category="location",
    )

    mock_llm = ScriptedGraphLLM(
        entities_by_chapter={
            1: [
                {"source_term": "张三", "entity_type": "character", "aliases": [], "evidence_snippet": "张三在青云山修炼。"},
                {"source_term": "青云山", "entity_type": "location", "aliases": [], "evidence_snippet": "张三在青云山修炼。"},
            ],
            2: [
                {"source_term": "张三", "entity_type": "character", "aliases": [], "evidence_snippet": "张三来到天云城。"},
                {"source_term": "天云城", "entity_type": "location", "aliases": [], "evidence_snippet": "张三来到天云城。"},
            ],
        },
        relationships_by_chapter={
            1: [
                {"type": "LOCATED_IN", "source_term": "张三", "target_term": "青云山", "evidence_snippet": "张三在青云山修炼。", "confidence": 0.9, "lore_text": None, "is_masked_identity": False},
            ],
            2: [
                {"type": "LOCATED_IN", "source_term": "张三", "target_term": "天云城", "evidence_snippet": "张三来到天云城。", "confidence": 0.9, "lore_text": None, "is_masked_identity": False},
            ],
        },
    )

    client = GraphClient(backend=InMemoryGraphBackend())
    result = preprocess_graph(
        release_id=release_id,
        run_id="graph-001",
        graph_client=client,
        llm_client=mock_llm,
    )
    assert result["status"] == "success"

    relationships = client.list_relationships(status="confirmed")
    loc_edges = [row for row in relationships if row.type == "LOCATED_IN"]
    assert len(loc_edges) == 2
    source_entity_id = loc_edges[0].source_entity_id

    chapter_1 = get_hierarchy_context(
        relationships=relationships,
        chapter_number=1,
        entity_id=source_entity_id,
    )
    chapter_2 = get_hierarchy_context(
        relationships=relationships,
        chapter_number=2,
        entity_id=source_entity_id,
    )

    assert len(chapter_1) == 1
    assert len(chapter_2) == 1
    assert chapter_1[0].target_entity_id != chapter_2[0].target_entity_id


def test_reveal_safe_lore_gating() -> None:
    relationship = GraphRelationship(
        relationship_id="rel_lore",
        release_id="rel",
        type="MEMBER_OF",
        source_entity_id="ent_a",
        target_entity_id="ent_b",
        source_chapter=1,
        start_chapter=1,
        end_chapter=None,
        revealed_chapter=3,
        confidence=0.8,
        status="confirmed",
        lore_text="第3章揭示其真实身份。",
        is_masked_identity=True,
        schema_version=1,
    )

    before_reveal = get_revealed_lore(
        relationships=[relationship],
        chapter_number=2,
    )
    after_reveal = get_revealed_lore(
        relationships=[relationship],
        chapter_number=3,
        masked_only=True,
    )

    assert before_reveal == []
    assert len(after_reveal) == 1
    assert after_reveal[0].is_masked_identity is True


def test_unsupported_world_model_expansion_is_rejected() -> None:
    validation = validate_graph_state(
        entities=[
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
        ],
        aliases=[],
        appearances=[],
        relationships=[
            GraphRelationship(
                relationship_id="rel_bad",
                release_id="rel",
                type="BROTHER_OF",
                source_entity_id="ent_a",
                target_entity_id="ent_b",
                source_chapter=1,
                start_chapter=1,
                end_chapter=None,
                revealed_chapter=1,
                confidence=0.8,
                status="confirmed",
                schema_version=1,
            )
        ],
    )
    assert not validation.is_valid
    assert any("unsupported_relationship_type" in err for err in validation.errors)


def test_local_world_model_selector_filters_non_local_edges() -> None:
    relationships = [
        GraphRelationship(
            relationship_id="rel_local",
            release_id="rel",
            type="MEMBER_OF",
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
            relationship_id="rel_global",
            release_id="rel",
            type="MEMBER_OF",
            source_entity_id="ent_a",
            target_entity_id="ent_c",
            source_chapter=1,
            start_chapter=1,
            end_chapter=None,
            revealed_chapter=1,
            confidence=0.8,
            status="confirmed",
            schema_version=1,
        ),
    ]
    selected = select_local_world_model_edges(
        relationships=relationships,
        chapter_number=2,
        local_entity_ids={"ent_a", "ent_b"},
    )
    assert [row.edge_id for row in selected] == ["rel_local"]
