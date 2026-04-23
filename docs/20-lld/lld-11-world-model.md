# LLD 11: Lightweight World Model (M7)

## Summary

Extend the graph with translation-support features: hierarchies, containment, role-state changes, and reveal-safe lore context.

## Public Interfaces

LadybugDB Edge Types:

- `MEMBER_OF` (Hierarchy)
- `LOCATED_IN` (Containment)
- `HELD_BY` (Item ownership/status)
- `RANKED_AS` (Role/Title status)

Python modules:

- `graph.models.WorldModelEdge`
- `graph.filters.get_hierarchy_context()`
- `graph.filters.get_revealed_lore()`

## Data Flow

1. Extraction logic identifies hierarchical or containment relationships from chapter summaries or source text.
2. Relationships are stored with chapter-scoped `start_chapter` and `end_chapter` to track role or title changes.
3. Reveal-safe lore facts (e.g., "Entity A is actually Entity B's brother") are stored with a `revealed_chapter` gate.
4. Confirmed world-model state is snapshotted for downstream packet assembly.
5. M8 packet assembly uses these edges to provide richer context for titles and factions.

## Validation Ownership

- graph schema enforces allowed world-model edge types
- validators reject future-knowledge leaks in lore context
- containment and hierarchy queries must respect chapter intervals

## Resume And Rerun

- world-model updates invalidate dependent chapter packets
- promotion of provisional world-model state follows the same rules as the graph MVP
- M7 completion produces confirmed graph state before M8 packet builds begin

## Tests

- role-state transition across chapters (e.g., character promoted from Disciple to Elder)
- containment visibility (e.g., character moves to a new city)
- reveal-safe lore context gating
