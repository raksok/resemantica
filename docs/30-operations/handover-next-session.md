# Handover Prompt: Resemantica (Post-M5)

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

M1, M2, M3, M4, and M5 are implemented and validated.

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
- Tests in `tests/epub/`, `tests/translation/`, `tests/glossary/`, `tests/summaries/`, and `tests/idioms/` passing.
- `docs/30-operations/repo-map.md` updated for real package layout.
- `IMPLEMENTATION_PLAN.md` M5 checklist updated to complete.

Verified commands from the previous session:

- `uv run --extra dev ruff check src\resemantica tests\idioms docs\30-operations\repo-map.md`
- `uv run --extra dev mypy src\resemantica`
- `uv run --extra dev pytest tests\idioms tests\summaries tests\glossary tests\translation tests\epub` (25 passed)
- `uv run python -m resemantica.cli preprocess --help` (shows glossary + summaries + idioms preprocess subcommands)
- `uv run python -m resemantica.cli preprocess idioms --help`

## Working Tree State (Not Committed Yet)

Current local changes:

- `IMPLEMENTATION_PLAN.md`
- `docs/30-operations/repo-map.md`
- `src/resemantica/cli.py`
- `src/resemantica/settings.py`
- `src/resemantica/db/idiom_repo.py`
- `src/resemantica/db/migrations/005_idioms.sql`
- `src/resemantica/idioms/` (new package)
- `src/resemantica/llm/prompts/idiom_detect.txt`
- `tests/idioms/`

## Runtime Test Note

- llama.cpp server is currently available at: `http://127.0.0.1:8033`
- If running live translation tests, point `llm.base_url` to this endpoint (default config currently uses `http://localhost:8080`).
- Live EPUB fixture available at: `tests/test_epub_src/Test_ebook.epub`
- If this fixture is used for live EPUB smoke tests, clean generated `artifacts/releases/<release_id>/` outputs after testing.
- `tests/test_epub_src/` is local-only and must not be pushed to remote.

## Next Objective

Start **M6** only:

- Task brief: `docs/40-tasks/task-06-graph-mvp.md`
- LLD: `docs/20-lld/lld-06-graph-mvp.md`

Focus for M6:

1. Implement Graph MVP foundation with LadybugDB-backed graph modules.
2. Add entity/alias/relationship storage and validation with chapter-safe and reveal-safe fields.
3. Enforce glossary authority linkage for glossary-covered categories.
4. Implement deferred-entity fallback lifecycle per `DECISIONS.md` D23.
5. Add chapter-safe filtering utilities and graph snapshot/hash support for downstream packet reproducibility.
6. Add tests for alias reveal gating, relationship eligibility, and provisional vs confirmed state separation.

## Existing M5 Files (orientation)

- `src/resemantica/idioms/` (`extractor.py`, `validators.py`, `matching.py`, `repo.py`, `pipeline.py`, `models.py`)
- `src/resemantica/db/idiom_repo.py`
- `src/resemantica/db/migrations/005_idioms.sql`
- `src/resemantica/llm/prompts/idiom_detect.txt`
- `tests/idioms/test_idiom_pipeline.py`

---
