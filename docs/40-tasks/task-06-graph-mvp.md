# Task 06: Graph MVP

- **Milestone:** M6
- **Depends on:** M1, M3, M4

## Goal

Implement the first graph slice for entities, aliases, appearances, and relationships with chapter-safe filtering.

## Scope

In:

- LadybugDB client wrapper
- provisional vs confirmed graph state
- packet-facing snapshot metadata

Out:

- rich lore reasoning
- live per-paragraph graph querying

## Owned Files Or Modules

- `src/resemantica/graph/`
- `tests/graph/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-06-graph-mvp.md`
- storage rules: `../10-architecture/storage-topology.md`
- glossary authority: locked glossary from Task 03 must be populated before graph extraction runs

## Tests Or Smoke Checks

- alias reveal gating
- chapter-safe relationship filter
- provisional/confirmed separation

## Done Criteria

- confirmed graph state can be exported or referenced for packet reproducibility
- graph validation rejects invalid references and ranges
- every confirmed entity in a glossary-covered category carries a valid `glossary_entry_id`
