# Handover Prompt: Resemantica (Post-M4)

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

M1, M2, M3, and M4 are implemented and validated.

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
- Tests in `tests/epub/`, `tests/translation/`, `tests/glossary/`, and `tests/summaries/` passing.
- `docs/30-operations/repo-map.md` updated for real package layout.

Verified commands from the previous session:

- `uv run --extra dev ruff check src\resemantica tests\glossary tests\translation tests\epub docs\30-operations\repo-map.md`
- `uv run --extra dev mypy src\resemantica`
- `uv run --extra dev pytest tests\summaries tests\glossary tests\translation tests\epub` (21 passed)
- `uv run python -m resemantica.cli --help` (shows `epub-roundtrip`, `translate-chapter`, `preprocess`)
- `uv run python -m resemantica.cli preprocess --help` (shows glossary + summaries preprocess subcommands)
- `uv run python -m resemantica.cli preprocess summaries --help`

## Runtime Test Note

- llama.cpp server is currently available at: `http://127.0.0.1:8033`
- If running live translation tests, point `llm.base_url` to this endpoint (default config currently uses `http://localhost:8080`).
- Live EPUB fixture available at: `tests/test_epub_src/Test_ebook.epub`
- If this fixture is used for live EPUB smoke tests, clean generated `artifacts/releases/<release_id>/` outputs after testing.
- `tests/test_epub_src/` is local-only and must not be pushed to remote.

## Next Objective

Start **M5** only:

- Task brief: `docs/40-tasks/task-05-idioms.md`
- LLD: `docs/20-lld/lld-05-idioms.md`

Focus for M5:

1. Implement idiom extraction and idiom policy repository in SQLite.
2. Keep idiom detection, validation, and policy promotion separated.
3. Add deterministic duplicate/conflict handling for idiom policy rows.
4. Add `preprocess idioms` CLI entrypoint per task + LLD.
5. Add tests for idiom detection, storage, and retrieval precedence hooks.

## Existing M4 Files (orientation)

- `src/resemantica/glossary/` (`discovery.py`, `validators.py`, `pipeline.py`, `models.py`)
- `src/resemantica/db/glossary_repo.py`
- `src/resemantica/db/migrations/003_glossary.sql`
- `src/resemantica/llm/prompts/glossary_translate.txt`, `glossary_discover.txt`
- `tests/glossary/test_glossary_pipeline.py`
- `src/resemantica/summaries/` (`generator.py`, `validators.py`, `derivation.py`, `pipeline.py`)
- `src/resemantica/db/summary_repo.py`
- `src/resemantica/db/migrations/004_summaries.sql`
- `src/resemantica/llm/prompts/summary_zh_structured.txt`, `summary_en_derive.txt`
- `tests/summaries/test_summary_pipeline.py`

---
