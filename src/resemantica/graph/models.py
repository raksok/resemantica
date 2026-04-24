from __future__ import annotations

from dataclasses import asdict, dataclass


GLOSSARY_COVERED_CATEGORIES: set[str] = {
    "character",
    "faction",
    "location",
    "technique",
    "item_artifact",
    "realm_concept",
    "creature_race",
    "event",
}

GRAPH_ENTITY_CATEGORIES: set[str] = {
    *GLOSSARY_COVERED_CATEGORIES,
    "title_honorific",
    "generic_role",
}

WORLD_MODEL_EDGE_TYPES: set[str] = {
    "MEMBER_OF",
    "LOCATED_IN",
    "HELD_BY",
    "RANKED_AS",
}

SUPPORTED_RELATIONSHIP_TYPES: set[str] = {
    "teacher_of",
    "ally_of",
    *WORLD_MODEL_EDGE_TYPES,
}


@dataclass(slots=True)
class GraphEntity:
    entity_id: str
    release_id: str
    entity_type: str
    canonical_name: str
    glossary_entry_id: str | None
    first_seen_chapter: int
    last_seen_chapter: int
    revealed_chapter: int
    status: str
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class GraphAlias:
    alias_id: str
    release_id: str
    entity_id: str
    alias_text: str
    alias_language: str
    first_seen_chapter: int
    last_seen_chapter: int
    revealed_chapter: int
    confidence: float
    is_masked_identity: bool
    status: str
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class GraphAppearance:
    appearance_id: str
    release_id: str
    entity_id: str
    chapter_number: int
    evidence_snippet: str
    status: str
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class GraphRelationship:
    relationship_id: str
    release_id: str
    type: str
    source_entity_id: str
    target_entity_id: str
    source_chapter: int
    start_chapter: int
    end_chapter: int | None
    revealed_chapter: int
    confidence: float
    status: str
    lore_text: str | None = None
    is_masked_identity: bool = False
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class WorldModelEdge:
    edge_id: str
    release_id: str
    edge_type: str
    source_entity_id: str
    target_entity_id: str
    source_chapter: int
    start_chapter: int
    end_chapter: int | None
    revealed_chapter: int
    confidence: float
    status: str
    lore_text: str | None = None
    is_masked_identity: bool = False
    schema_version: int = 1

    def to_graph_relationship(self) -> GraphRelationship:
        return GraphRelationship(
            relationship_id=self.edge_id,
            release_id=self.release_id,
            type=self.edge_type,
            source_entity_id=self.source_entity_id,
            target_entity_id=self.target_entity_id,
            source_chapter=self.source_chapter,
            start_chapter=self.start_chapter,
            end_chapter=self.end_chapter,
            revealed_chapter=self.revealed_chapter,
            confidence=self.confidence,
            status=self.status,
            lore_text=self.lore_text,
            is_masked_identity=self.is_masked_identity,
            schema_version=self.schema_version,
        )

    @classmethod
    def from_graph_relationship(cls, relationship: GraphRelationship) -> WorldModelEdge:
        if relationship.type not in WORLD_MODEL_EDGE_TYPES:
            raise ValueError(
                f"Relationship {relationship.relationship_id} is not a world-model edge: {relationship.type}"
            )
        return cls(
            edge_id=relationship.relationship_id,
            release_id=relationship.release_id,
            edge_type=relationship.type,
            source_entity_id=relationship.source_entity_id,
            target_entity_id=relationship.target_entity_id,
            source_chapter=relationship.source_chapter,
            start_chapter=relationship.start_chapter,
            end_chapter=relationship.end_chapter,
            revealed_chapter=relationship.revealed_chapter,
            confidence=relationship.confidence,
            status=relationship.status,
            lore_text=relationship.lore_text,
            is_masked_identity=relationship.is_masked_identity,
            schema_version=relationship.schema_version,
        )

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class DeferredEntityRecord:
    deferred_id: str
    release_id: str
    term_text: str
    normalized_term_text: str
    category: str
    evidence_snippet: str
    source_chapter: int
    last_seen_chapter: int
    appearance_count: int
    status: str
    glossary_entry_id: str | None
    discovered_at: str | None = None
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class GraphSnapshotRecord:
    snapshot_id: str
    release_id: str
    snapshot_hash: str
    graph_db_path: str
    entity_count: int
    alias_count: int
    appearance_count: int
    relationship_count: int
    created_at: str | None = None
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)
