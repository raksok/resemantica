from __future__ import annotations

from dataclasses import dataclass, field

from resemantica.graph.models import (
    GLOSSARY_COVERED_CATEGORIES,
    GraphAlias,
    GraphAppearance,
    GraphEntity,
    GraphRelationship,
)


@dataclass(slots=True)
class GraphValidationResult:
    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.status == "success"


def validate_graph_state(
    *,
    entities: list[GraphEntity],
    aliases: list[GraphAlias],
    appearances: list[GraphAppearance],
    relationships: list[GraphRelationship],
) -> GraphValidationResult:
    errors: list[str] = []

    entity_ids = {entity.entity_id for entity in entities}
    if len(entity_ids) != len(entities):
        errors.append("graph_invalid: duplicate entity_id detected")

    for entity in entities:
        if entity.first_seen_chapter > entity.last_seen_chapter:
            errors.append(
                f"chapter_range_invalid: entity {entity.entity_id} first_seen_chapter > last_seen_chapter"
            )
        if entity.revealed_chapter > entity.last_seen_chapter:
            errors.append(
                f"chapter_range_invalid: entity {entity.entity_id} revealed_chapter > last_seen_chapter"
            )
        if (
            entity.status == "confirmed"
            and entity.entity_type in GLOSSARY_COVERED_CATEGORIES
            and not entity.glossary_entry_id
        ):
            errors.append(
                f"glossary_link_missing: confirmed entity {entity.entity_id} in category "
                f"{entity.entity_type} must include glossary_entry_id"
            )

    for alias in aliases:
        if alias.entity_id not in entity_ids:
            errors.append(
                f"dangling_reference: alias {alias.alias_id} references missing entity {alias.entity_id}"
            )
        if alias.first_seen_chapter > alias.last_seen_chapter:
            errors.append(
                f"chapter_range_invalid: alias {alias.alias_id} first_seen_chapter > last_seen_chapter"
            )
        if alias.revealed_chapter > alias.last_seen_chapter:
            errors.append(
                f"chapter_range_invalid: alias {alias.alias_id} revealed_chapter > last_seen_chapter"
            )

    for appearance in appearances:
        if appearance.entity_id not in entity_ids:
            errors.append(
                f"dangling_reference: appearance {appearance.appearance_id} references missing entity {appearance.entity_id}"
            )
        if appearance.chapter_number <= 0:
            errors.append(
                f"chapter_range_invalid: appearance {appearance.appearance_id} chapter_number must be > 0"
            )

    for relationship in relationships:
        if relationship.source_entity_id not in entity_ids:
            errors.append(
                f"dangling_reference: relationship {relationship.relationship_id} missing source_entity_id "
                f"{relationship.source_entity_id}"
            )
        if relationship.target_entity_id not in entity_ids:
            errors.append(
                f"dangling_reference: relationship {relationship.relationship_id} missing target_entity_id "
                f"{relationship.target_entity_id}"
            )
        if relationship.end_chapter is not None and relationship.start_chapter > relationship.end_chapter:
            errors.append(
                f"chapter_range_invalid: relationship {relationship.relationship_id} start_chapter > end_chapter"
            )
        if relationship.revealed_chapter < relationship.start_chapter:
            errors.append(
                f"chapter_range_invalid: relationship {relationship.relationship_id} revealed_chapter "
                "is earlier than start_chapter"
            )
        if (
            relationship.end_chapter is not None
            and relationship.revealed_chapter > relationship.end_chapter
        ):
            errors.append(
                f"chapter_range_invalid: relationship {relationship.relationship_id} revealed_chapter > end_chapter"
            )
        if relationship.source_chapter < relationship.start_chapter:
            errors.append(
                f"chapter_range_invalid: relationship {relationship.relationship_id} source_chapter < start_chapter"
            )
        if (
            relationship.end_chapter is not None
            and relationship.source_chapter > relationship.end_chapter
        ):
            errors.append(
                f"chapter_range_invalid: relationship {relationship.relationship_id} source_chapter > end_chapter"
            )

    return GraphValidationResult(
        status="failed" if errors else "success",
        errors=errors,
        warnings=[],
    )

