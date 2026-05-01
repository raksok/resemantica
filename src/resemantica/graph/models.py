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
    "ALIAS_OF",
    "APPEARS_IN",
    "DISCIPLE_OF",
    "MASTER_OF",
    "ALLY_OF",
    "ENEMY_OF",
    "OWNS",
    "USES_TECHNIQUE",
    "PART_OF_ARC",
    "NEXT_CHAPTER",
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


def validate_world_model_edge(rel: GraphRelationship) -> None:
    if rel.type not in WORLD_MODEL_EDGE_TYPES:
        raise ValueError(
            f"Relationship {rel.relationship_id} is not a world-model edge: {rel.type}"
        )


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
