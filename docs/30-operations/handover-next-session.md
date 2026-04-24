# Handover Prompt: Resemantica (Post-M6)

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

M1, M2, M3, M4, M5, and M6 are implemented and validated.

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
- M3 glossary flow includes:
  - glossary candidate discovery from extracted chapter artifacts
  - candidate translation with prompt version/model provenance
  - deterministic validation (normalization, naming policy, duplicate/conflict checks)
  - transactional promotion to locked glossary
  - conflict recording and exact-match precedence helper
- M4 summary flow includes:
  - `summary_drafts`, `validated_summaries_zh`, `derived_summaries_en` repositories in SQLite
  - structured Chinese summary generation with deterministic validation gates
  - atomic materialization of `chapter_summary_zh_structured` + `chapter_summary_zh_short`
  - deterministic `story_so_far_zh` derivation from validated Chinese short summaries only
  - derived English summaries with persisted provenance hashes (`source_summary_hash`, `glossary_version_hash`)
- M5 idiom flow includes:
  - idiom extraction from extracted chapter artifacts via analyst prompt
  - separated detection, validation, and promotion stages
  - SQLite candidate/policy/conflict storage with deterministic duplicate/conflict handling
  - exact-match idiom retrieval hook and matching helper
- M6 graph flow includes:
  - graph models, extraction, validation, and chapter-safe filter utilities
  - Ladybug graph client wrapper and snapshot hash export metadata
  - deterministic glossary-anchored entity extraction
  - deferred entity fallback lifecycle in SQLite (`pending_glossary` → `promoted` → `graph_created`)
  - `preprocess graph` CLI entrypoint and graph artifact snapshots
- Tests in `tests/epub/`, `tests/translation/`, `tests/glossary/`, `tests/summaries/`, `tests/idioms/`, and `tests/graph/` passing.
- `docs/30-operations/repo-map.md` updated for real package layout.
- `IMPLEMENTATION_PLAN.md` M6 checklist updated to complete.

Verified commands from the previous session:

- `uv run --extra dev ruff check src\resemantica tests\graph docs\30-operations\repo-map.md`
- `uv run --extra dev mypy src\resemantica`
- `uv run --extra dev pytest tests\graph tests\idioms tests\summaries tests\glossary tests\translation tests\epub` (30 passed)
- `uv run python -m resemantica.cli preprocess --help` (shows glossary + summaries + idioms + graph preprocess subcommands)
- `uv run python -m resemantica.cli preprocess graph --help`

## Working Tree State (Not Committed Yet)

Current local changes:

- `IMPLEMENTATION_PLAN.md`
- `docs/30-operations/repo-map.md`
- `src/resemantica/cli.py`
- `src/resemantica/settings.py`
- `src/resemantica/db/graph_repo.py`
- `src/resemantica/db/migrations/006_graph.sql`
- `src/resemantica/graph/` (new package)
- `tests/graph/`

## Runtime Test Note

- llama.cpp server is currently available at: `http://127.0.0.1:8033`
- If running live translation tests, point `llm.base_url` to this endpoint (default config currently uses `http://localhost:8080`).
- Live EPUB fixture available at: `tests/test_epub_src/Test_ebook.epub`
- If this fixture is used for live EPUB smoke tests, clean generated `artifacts/releases/<release_id>/` outputs after testing.
- `tests/test_epub_src/` is local-only and must not be pushed to remote.

## Next Objective

Start **M7** only:

- Task brief: `docs/40-tasks/task-07-world-model.md`
- LLD: `docs/20-lld/lld-07-world-model.md`

Focus for M7:

1. Extend graph schema with world-model edge types (`MEMBER_OF`, `LOCATED_IN`, `HELD_BY`, `RANKED_AS`).
2. Implement chapter-scoped role-state transitions and containment/hierarchy handling.
3. Add reveal-safe lore gating behavior that blocks future-knowledge leaks.
4. Keep provisional vs confirmed promotion behavior consistent with M6 graph MVP.
5. Ensure world-model updates remain snapshot-ready for M8 packet assembly.
6. Add tests for role-state transitions, containment visibility, reveal-safe lore gating, and unsupported world-model rejection.

## Existing M6 Files (orientation)

- `src/resemantica/graph/` (`models.py`, `client.py`, `extractor.py`, `validators.py`, `filters.py`, `pipeline.py`)
- `src/resemantica/db/graph_repo.py`
- `src/resemantica/db/migrations/006_graph.sql`
- `tests/graph/test_graph_pipeline.py`

---
