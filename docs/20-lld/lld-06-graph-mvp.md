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

SQLite datasets:

- `deferred_entities`
- `graph_snapshots`
- `graph_extraction_drafts`

## Data Flow

1. Read extracted chapter content with glossary anchors and summaries.
2. Cross-reference extracted entities against the locked glossary. For glossary-covered categories (character, faction, location, technique, item_artifact, realm_concept, creature_race, event), attach `glossary_entry_id` at extraction time. For terms with no locked glossary entry: do **not** create a LadybugDB node — instead, write a `deferred_entity` record to SQLite with `status = 'pending_glossary'`, the term text, category, evidence snippet, and source chapter. Emit a `warning_emitted` event noting the deferred term. Re-running graph extraction after glossary promotion resolves pending deferred entries (see D23).
3. **Content validation**: entity names are checked (a) contain only CJK characters, no Latin mixed in, and (b) actually appear in the chapter source text. Violations are skipped with a warning.
4. Build provisional entity and relationship observations.
5. Validate references, intervals, and reveal metadata.
6. Promote confirmed graph state.
7. Export snapshot metadata for packet reproducibility.
8. Feed `preprocess-continuity` as the long-horizon continuity authority after graph validation. The graph remains the source of chapter-safe anchors; no separate memory ledger is introduced.

## Analyst Prompt Optimization

`graph_extract.txt` remains schema-compatible but is optimized for compact extraction:

- output raw JSON only, with no markdown, prose analysis, chain-of-thought, or `<think>` artifacts
- extract significant named entities and evidenced relationships only
- keep evidence snippets short
- avoid speculative relationships added only to satisfy coverage
- preserve Chinese-only `source_term`, alias, evidence, and relationship term fields

## Content Validation

Three deterministic guardrails applied at entity extraction time (in `graph/extractor.py`):

### CJK-Only Entity Names

Entity `source_term` values containing ASCII Latin letters (`[A-Za-z]`) are rejected. Prevents mixed-language output like "青云门 Azure Sect" from entering the graph. Emits a `WARN` to stdout.

### Source-Text Cross-Reference

Each entity `source_term` must appear as a substring in the chapter's source text. Prevents pure-hallucinated entity names. Emits a `WARN` if not found.

### Alias Language Detection

Alias `alias_language` is detected from content rather than hardcoded:
- Contains CJK characters → `"zh"`
- Latin-only → `"en"`
- Otherwise → `"zh"` (default)

## Validation Ownership

- only confirmed graph state may feed packets
- reveal intervals and chapter eligibility are deterministic filter logic
- graph validation rejects dangling references and invalid chapter ranges

## Resume And Rerun

- graph exports used by packets must be identifiable by snapshot hash or version
- graph snapshots are required before `preprocess-continuity` can refresh `story_so_far_zh_graph_compact`
- provisional graph state may be rerun without mutating confirmed graph state
- extraction drafts are persisted per release, run, chapter, chapter source hash, and graph prompt version
- resume skips chapter extraction when a matching draft row exists, merges requested drafts in chapter order, validates, and writes confirmed graph state plus a new snapshot
- draft merging preserves cross-chapter relationship intervals before validation
- `run retry-failed --stage preprocess-graph` retries chapters missing graph extraction drafts. If extraction drafts exist but the stage failed during merge or validation, the existing drafts are reused and merge/validation runs again.
- `--force` deletes or ignores matching draft rows for the requested scope before extraction

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
