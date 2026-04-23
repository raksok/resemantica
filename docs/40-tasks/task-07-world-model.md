# Task 07: Lightweight World Model

- **Milestone:** M7
- **Depends on:** M6

## Goal

Extend the confirmed graph state with translation-support world-model features before chapter packets are built in M8.

## Scope

In:

- hierarchy, containment, and role-state relationship types
- chapter-scoped relationship intervals
- reveal-safe lore facts and masked-identity gates
- snapshot-ready confirmed graph state for packet assembly

Out:

- general ontology modeling
- agentic reasoning over world state
- packet assembly implementation

## Owned Files Or Modules

- `src/resemantica/graph/`
- `tests/graph/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-07-world-model.md`
- graph MVP contracts from `../20-lld/lld-06-graph-mvp.md`
- storage rules: `../10-architecture/storage-topology.md`

## Tests Or Smoke Checks

- role-state transition across chapter intervals
- containment visibility by chapter
- reveal-safe lore gating
- unsupported world-model expansion is rejected

## Done Criteria

- confirmed graph state can track changing titles, containment, and hierarchy relationships
- reveal-safe lore appears only at or after its allowed chapter
- world-model state is snapshot-ready for M8 packet builds
- additions stay within translation-support scope
