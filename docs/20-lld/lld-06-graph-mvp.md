# LLD 06: Graph MVP

## Summary

Add a narrow graph layer for entities, aliases, appearances, and relationships that support translation continuity and packet assembly without turning the system into a lore engine.

> **IMPORTANT:** The graph database is **LadybugDB** (`import ladybug as lb`). Do NOT use `import kuzu`. See DECISIONS.md C9 for full details.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli preprocess graph --release <release_id>`

Python modules:

- `graph.client` — wraps `ladybug` package (`import ladybug as lb`)
- `graph.extractor.extract_entities()`
- `graph.validators.validate_graph_state()`
- `graph.filters.filter_for_chapter()`

LadybugDB datasets:

- entities
- aliases
- appearances
- relationships

## Data Flow

1. Read extracted chapter content with glossary anchors and summaries.
2. Cross-reference extracted entities against the locked glossary. For glossary-covered categories (character, faction, location, technique, item_artifact, realm_concept, creature_race, event), attach `glossary_entry_id` at extraction time. For terms with no locked glossary entry: do **not** create a LadybugDB node — instead, write a `deferred_entity` record to SQLite with `status = 'pending_glossary'`, the term text, category, evidence snippet, and source chapter. Emit a `warning_emitted` event noting the deferred term. Re-running graph extraction after glossary promotion resolves pending deferred entries (see D23).
3. Build provisional entity and relationship observations.
4. Validate references, intervals, and reveal metadata.
5. Promote confirmed graph state.
6. Export snapshot metadata for packet reproducibility.

## Validation Ownership

- only confirmed graph state may feed packets
- reveal intervals and chapter eligibility are deterministic filter logic
- graph validation rejects dangling references and invalid chapter ranges

## Resume And Rerun

- graph exports used by packets must be identifiable by snapshot hash or version
- provisional graph state may be rerun without mutating confirmed graph state

## Tests

- alias reveal gating
- chapter-safe relationship filtering
- separation between provisional and confirmed graph state
- entity extraction defers unmatched glossary-covered terms to `deferred_entity` SQLite table
- deferred entity status lifecycle: pending_glossary → promoted → graph_created
- snapshot metadata available for packet reproducibility

## Out Of Scope

- broad world simulation
- per-paragraph heavy live graph querying
