from __future__ import annotations

from dataclasses import dataclass

from resemantica.graph.models import (
    GraphAlias,
    GraphAppearance,
    GraphEntity,
    GraphRelationship,
    WORLD_MODEL_EDGE_TYPES,
    WorldModelEdge,
)


@dataclass(slots=True)
class GraphChapterView:
    entities: list[GraphEntity]
    aliases: list[GraphAlias]
    appearances: list[GraphAppearance]
    relationships: list[GraphRelationship]


def filter_for_chapter(
    *,
    entities: list[GraphEntity],
    aliases: list[GraphAlias],
    appearances: list[GraphAppearance],
    relationships: list[GraphRelationship],
    chapter_number: int,
) -> GraphChapterView:
    eligible_entities = [
        entity
        for entity in entities
        if entity.status == "confirmed"
        and entity.first_seen_chapter <= chapter_number <= entity.last_seen_chapter
        and entity.revealed_chapter <= chapter_number
    ]
    entity_ids = {entity.entity_id for entity in eligible_entities}

    eligible_aliases = [
        alias
        for alias in aliases
        if alias.status == "confirmed"
        and alias.entity_id in entity_ids
        and alias.first_seen_chapter <= chapter_number <= alias.last_seen_chapter
        and alias.revealed_chapter <= chapter_number
    ]

    eligible_appearances = [
        appearance
        for appearance in appearances
        if appearance.status == "confirmed"
        and appearance.entity_id in entity_ids
        and appearance.chapter_number <= chapter_number
    ]

    eligible_relationships = [
        relationship
        for relationship in relationships
        if relationship.status == "confirmed"
        and relationship.source_entity_id in entity_ids
        and relationship.target_entity_id in entity_ids
        and relationship.start_chapter <= chapter_number
        and (relationship.end_chapter is None or relationship.end_chapter >= chapter_number)
        and relationship.revealed_chapter <= chapter_number
    ]

    return GraphChapterView(
        entities=sorted(eligible_entities, key=lambda row: row.entity_id),
        aliases=sorted(eligible_aliases, key=lambda row: row.alias_id),
        appearances=sorted(
            eligible_appearances,
            key=lambda row: (row.chapter_number, row.appearance_id),
        ),
        relationships=sorted(eligible_relationships, key=lambda row: row.relationship_id),
    )


def _relationship_visible_for_chapter(
    relationship: GraphRelationship,
    *,
    chapter_number: int,
) -> bool:
    return (
        relationship.status == "confirmed"
        and relationship.start_chapter <= chapter_number
        and (relationship.end_chapter is None or relationship.end_chapter >= chapter_number)
        and relationship.revealed_chapter <= chapter_number
    )


def get_hierarchy_context(
    *,
    relationships: list[GraphRelationship],
    chapter_number: int,
    entity_id: str | None = None,
) -> list[WorldModelEdge]:
    visible_edges = [
        relationship
        for relationship in relationships
        if relationship.type in WORLD_MODEL_EDGE_TYPES
        and _relationship_visible_for_chapter(relationship, chapter_number=chapter_number)
        and (entity_id is None or relationship.source_entity_id == entity_id)
    ]
    return [
        WorldModelEdge.from_graph_relationship(relationship)
        for relationship in sorted(
            visible_edges,
            key=lambda row: (row.type, row.source_entity_id, row.target_entity_id, row.relationship_id),
        )
    ]


def get_revealed_lore(
    *,
    relationships: list[GraphRelationship],
    chapter_number: int,
    masked_only: bool = False,
) -> list[WorldModelEdge]:
    visible_lore_edges = [
        relationship
        for relationship in relationships
        if relationship.type in WORLD_MODEL_EDGE_TYPES
        and _relationship_visible_for_chapter(relationship, chapter_number=chapter_number)
        and relationship.lore_text is not None
        and relationship.lore_text.strip()
        and (not masked_only or relationship.is_masked_identity)
    ]
    return [
        WorldModelEdge.from_graph_relationship(relationship)
        for relationship in sorted(
            visible_lore_edges,
            key=lambda row: (row.revealed_chapter, row.relationship_id),
        )
    ]


def select_local_world_model_edges(
    *,
    relationships: list[GraphRelationship],
    chapter_number: int,
    local_entity_ids: set[str],
) -> list[WorldModelEdge]:
    selected = [
        relationship
        for relationship in relationships
        if relationship.type in WORLD_MODEL_EDGE_TYPES
        and _relationship_visible_for_chapter(relationship, chapter_number=chapter_number)
        and relationship.source_entity_id in local_entity_ids
        and relationship.target_entity_id in local_entity_ids
    ]
    return [
        WorldModelEdge.from_graph_relationship(relationship)
        for relationship in sorted(selected, key=lambda row: row.relationship_id)
    ]
