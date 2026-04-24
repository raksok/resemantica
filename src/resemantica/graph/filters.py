from __future__ import annotations

from dataclasses import dataclass

from resemantica.graph.models import GraphAlias, GraphAppearance, GraphEntity, GraphRelationship


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

