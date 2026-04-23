# Handover Prompt: Resemantica (Post-M3)

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

M1, M2, and M3 are implemented and validated.

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
- M2 translation flow includes Pass 1 + Pass 2, validation artifacts, checkpoint resume, and reactive resegmentation.
- M3 glossary flow includes:
  - glossary candidate discovery from extracted chapter artifacts
  - candidate translation with prompt version/model provenance
  - deterministic validation (normalization, naming policy, duplicate/conflict checks)
  - transactional promotion to locked glossary
  - conflict recording and exact-match precedence helper
- Tests in `tests/epub/`, `tests/translation/`, and `tests/glossary/` passing.
- `docs/30-operations/repo-map.md` updated for real package layout.

Verified commands from the previous session:

- `uv run --extra dev ruff check src\resemantica tests\glossary tests\translation tests\epub docs\30-operations\repo-map.md`
- `uv run --extra dev mypy src\resemantica`
- `uv run --extra dev pytest tests\glossary tests\translation tests\epub` (16 passed)
- `uv run python -m resemantica.cli --help` (shows `epub-roundtrip`, `translate-chapter`, `preprocess`)
- `uv run python -m resemantica.cli preprocess --help` (shows glossary preprocess subcommands)

## Runtime Test Note

- llama.cpp server is currently available at: `http://127.0.0.1:8033`
- If running live translation tests, point `llm.base_url` to this endpoint (default config currently uses `http://localhost:8080`).
- Live EPUB fixture available at: `tests/test_epub_src/Test_ebook.epub`
- If this fixture is used for live EPUB smoke tests, clean generated `artifacts/releases/<release_id>/` outputs after testing.

## Next Objective

Start **M4** only:

- Task brief: `docs/40-tasks/task-04-summaries.md`
- LLD: `docs/20-lld/lld-04-summaries.md`

Focus for M4:

1. Build summary repositories for structured/draft and validated continuity layers.
2. Implement Chinese summary generation and deterministic validation gates.
3. Materialize `chapter_summary_zh_structured` and `chapter_summary_zh_short` as distinct rows.
4. Implement `story_so_far_zh` derivation from validated Chinese continuity only.
5. Add tests for continuity conflicts, terminology checks against locked glossary, and future-knowledge leak checks.

## Existing M3 Files (orientation)

- `src/resemantica/glossary/` (`discovery.py`, `validators.py`, `pipeline.py`, `models.py`)
- `src/resemantica/db/glossary_repo.py`
- `src/resemantica/db/migrations/003_glossary.sql`
- `src/resemantica/llm/prompts/glossary_translate.txt`, `glossary_discover.txt`
- `tests/glossary/test_glossary_pipeline.py`

---
