# Handover Prompt: Resemantica (Post-M7)

Use this prompt in the next session:

---

You are continuing implementation of **Resemantica** in `D:\Project\resemantica`.

## Non-Negotiable Rules

- Follow `AGENTS.md` and `docs/30-operations/agent-workflow.md`.
- Execute milestones strictly in order (M1 → M14).
- Use `DECISIONS.md` as the implementation authority when docs conflict.
- Use **LadybugDB** only (`import ladybug as lb`), never `kuzu`.
- Make surgical changes only; do not refactor unrelated code.

## Current Status

M1, M2, M3, M4, M5, M6, and M7 are implemented and validated.

Completed and verified:

- EPUB unpack + OPF/spine discovery + deterministic rebuild.
- XHTML parsing and block extraction with stable IDs/order.
- Placeholder extraction/restoration with nested-map fields:
  - `parent_placeholder`
  - `closing_order`
- Segment splitting with `_seg{NN}` IDs and `parent_block_id`.
- CLI commands: `epub-roundtrip`, `translate-chapter`, and `preprocess` with:
  - `glossary-discover`
  - `glossary-translate`
  - `glossary-promote`
  - `summaries`
  - `idioms`
  - `graph`
- M2 translation flow includes Pass 1 + Pass 2, validation artifacts, checkpoint resume, and reactive resegmentation.
- M3 glossary flow includes deterministic validation and transactional promotion.
- M4 summary flow includes authority/derived separation and deterministic continuity derivation.
- M5 idiom flow includes separated detection/validation/promotion with exact-match retrieval hook.
- M6 graph flow includes glossary-anchored entity extraction, deferred entity lifecycle, chapter-safe filtering, and snapshot metadata.
- M7 world-model flow includes:
  - world-model edge types (`MEMBER_OF`, `LOCATED_IN`, `HELD_BY`, `RANKED_AS`)
  - chapter-scoped role-state transition handling
  - reveal-safe lore gating helpers
  - unsupported relationship-type rejection in validators
  - local world-model edge selector for packet-facing integration
- Tests in `tests/epub/`, `tests/translation/`, `tests/glossary/`, `tests/summaries/`, `tests/idioms/`, and `tests/graph/` passing.
- `docs/30-operations/repo-map.md` updated for real package layout.
- `IMPLEMENTATION_PLAN.md` M7 checklist updated to complete.

Verified commands from the previous session:

- `uv run --extra dev ruff check src\resemantica tests\graph docs\30-operations\repo-map.md`
- `uv run --extra dev mypy src\resemantica`
- `uv run --extra dev pytest tests\graph tests\idioms tests\summaries tests\glossary tests\translation tests\epub` (35 passed)
- `uv run python -m resemantica.cli preprocess --help` (shows glossary + summaries + idioms + graph preprocess subcommands)
- `uv run python -m resemantica.cli preprocess graph --help`

## Working Tree State

- After committing this session’s changes, working tree should be clean.
- No push has been performed.

## Runtime Test Note

- llama.cpp server is currently available at: `http://127.0.0.1:8033`
- If running live translation tests, point `llm.base_url` to this endpoint (default config currently uses `http://localhost:8080`).
- Live EPUB fixture available at: `tests/test_epub_src/Test_ebook.epub`
- If this fixture is used for live EPUB smoke tests, clean generated `artifacts/releases/<release_id>/` outputs after testing.
- `tests/test_epub_src/` is local-only and must not be pushed to remote.

## Next Objective

Start **M8** only:

- Task brief: `docs/40-tasks/task-08-packets.md`
- LLD: `docs/20-lld/lld-08-packets.md`

Focus for M8:

1. Implement immutable chapter packet schemas and packet metadata persistence.
2. Build packet assembly using locked glossary, validated summaries, idiom policies, and confirmed graph context.
3. Add chapter-safe graph context compaction (no unrestricted subgraph dumps).
4. Implement packet size budgeting and degrade-order trimming with token counting safety rules.
5. Build narrow paragraph bundles and enforce retrieval precedence (glossary/idiom over graph).
6. Add stale packet detection based on upstream hashes (including graph snapshot hash).
7. Add tests for schema validity, provenance hashes, graph-to-packet filtering, size control, and stale rebuild triggers.

## Existing M7 Files (orientation)

- `src/resemantica/graph/` (`models.py`, `client.py`, `extractor.py`, `validators.py`, `filters.py`, `pipeline.py`)
- `src/resemantica/db/graph_repo.py`
- `src/resemantica/db/migrations/006_graph.sql`
- `tests/graph/test_graph_pipeline.py`

---

