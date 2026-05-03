# Task 06: Graph MVP

- **Milestone:** M6
- **Depends on:** M1, M3, M4
- **Status:** Completed on 2026-04-28 (implementation + validation complete)
- **Post-MVP Improvements:** 2026-05-03

## Goal

Implement the first graph slice for entities, aliases, appearances, and relationships with chapter-safe filtering.

## Scope

In:

- LadybugDB client wrapper
- provisional vs confirmed graph state
- packet-facing snapshot metadata
- content validation guardrails (CJK-only entity names, source-text cross-reference, alias language detection)

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

## Post-MVP Improvements (2026-05-03)

Content validation guardrails added to entity extraction:

### 1. CJK-Only Entity Names

Entity `source_term` values containing Latin characters (e.g. "青云门 Azure Sect") are rejected with a warning. The LLM prompt requests "exact Chinese text" but was not enforced — this makes it deterministic.

### 2. Source-Text Cross-Reference

Each entity name is checked against the chapter source text. If `source_term` does not appear as a substring in the chapter text, the entity is skipped with a warning. This catches pure-hallucinated entity names.

### 3. Alias Language Detection

Alias `alias_language` is now detected from content rather than hardcoded to "zh". Uses CJK regex: if the alias contains CJK characters → "zh", if Latin-only → "en", otherwise defaults to "zh".
