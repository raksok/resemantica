# LLD 05: Chapter Packets with Graph Integration (M8)

## Summary

Build immutable chapter packets from validated upstream memory, including confirmed graph state from M6 and M7, then derive narrow paragraph bundles for translation-time use.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli packets build --release <release_id> [--chapter <n>]`

Python modules:

- `packets.builder.build_chapter_packet()`
- `packets.builder.enrich_with_graph_context()`
- `packets.bundler.build_paragraph_bundle()`
- `packets.invalidation.detect_stale_packet()`

Artifacts:

- chapter packet JSON
- packet metadata row
- paragraph bundle JSON or derived in-memory object with matching schema

## Packet Contents

Minimum packet sections:

- chapter metadata
- locked glossary slice relevant to the chapter
- validated continuity summaries
- idiom policy slice
- graph snapshot reference and compact graph-derived context
- chapter-safe relationship snippets
- alias resolution candidates
- reveal-safe identity and lore notes
- provenance hashes

## Data Flow

1. Load validated upstream authority datasets.
2. Load confirmed graph state through chapter-safe filters.
3. Identify active entities for chapter `N` from chapter source, glossary hits, summaries, and recent context.
4. Compact eligible graph context into packet sections without dumping unrestricted subgraphs.
5. Call `llm.tokens.count_tokens()` on each assembled packet section. If the total exceeds `max_context_per_pass` (49152), trim sections following the degrade order (`broad_continuity` → `fuzzy_candidates` → `rerank_depth` → `pass3` → `fallback_model`) until under budget.
6. Build chapter packet JSON with all required hashes.
7. Persist packet metadata in SQLite.
8. Derive paragraph bundles from local packet sections and source block context. Count tokens per bundle; if a bundle exceeds `max_bundle_bytes`, trim lower-priority retrieval evidence.
9. Apply retrieval arbitration so locked glossary and deterministic idioms outrank graph suggestions.
10. Refuse broad full-chapter dumps in bundle output.

## Validation Ownership

- packet builder validates presence of required upstream hashes
- graph context must be filtered by chapter before packet storage
- packet size limits must trim lower-priority graph context before authority context
- bundle builder enforces narrow context limits
- retrieval arbitration must prefer glossary, explicit aliases, and deterministic idiom matches over graph-derived suggestions
- packet metadata and artifact hash must match

## Resume And Rerun

- packets are immutable artifacts
- upstream hash change marks packet stale
- graph snapshot hash change marks dependent packets stale
- stale packets must be rebuilt before dependent translation reruns

## Tests

- packet schema validity
- required provenance fields present
- bundle excludes non-local or future chapter context
- graph-to-packet filtering
- retrieval precedence conflicts
- packet size budgeting
- stale packet detection when upstream hash changes

## Out Of Scope

- live graph query-heavy translation
- Pass 3 behavior
