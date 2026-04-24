# Handover Prompt: Resemantica (Post-M9)

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

M1, M2, M3, M4, M5, M6, M7, M8, and M9 are implemented and validated.

Completed and verified:

- EPUB unpack + OPF/spine discovery + deterministic rebuild.
- XHTML parsing and block extraction with stable IDs/order.
- Placeholder extraction/restoration with nested-map fields:
  - `parent_placeholder`
  - `closing_order`
- Segment splitting with `_seg{NN}` IDs and `parent_block_id`.
- CLI commands:
  - `epub-roundtrip`
  - `translate-chapter`
  - `preprocess` (`glossary-discover`, `glossary-translate`, `glossary-promote`, `summaries`, `idioms`, `graph`)
  - `packets build`
- M2 translation flow includes Pass 1 + Pass 2, validation artifacts, checkpoint resume, and reactive resegmentation.
- M3 glossary flow includes deterministic validation and transactional promotion.
- M4 summary flow includes authority/derived separation and deterministic continuity derivation.
- M5 idiom flow includes separated detection/validation/promotion with exact-match retrieval hook.
- M6 graph flow includes glossary-anchored entity extraction, deferred entity lifecycle, chapter-safe filtering, and snapshot metadata.
- M7 world-model flow includes supported world-model edge types, role-state transitions, reveal-safe lore gating, and unsupported relationship rejection.
- M8 packet flow includes:
  - immutable chapter packet + paragraph bundle schemas
  - SQLite packet metadata persistence
  - chapter-safe graph compaction for packet context
  - packet/bundle size budgeting with D22 5% safety buffer
  - retrieval precedence where glossary/idiom authority outranks graph alias suggestions
  - stale detection and stale rebuild behavior based on upstream hashes
  - packet CLI wiring (`packets build`)
- M9 Pass 3 + risk flow includes:
  - `translation.pass3.translate_pass3()` readability polish with fidelity/terminology guardrails
  - `translation.risk.classify_paragraph_risk()` deterministic D21 weighted formula with all sub-scores persisted
  - High-risk skip behavior (risk >= 0.7) where final output remains validated Pass 2 output
  - `translation.validators.validate_pass3_integrity()` catches terminology drift and placeholder mismatch
  - Pass 3 integrity fallback to Pass 2 output on validation failure
  - Pass 3 artifacts (`pass3.json`) with risk classifications, integrity checks, and pass decisions per block
  - Chapter-level validation report (`chapter.json`) with pass statuses, risk classifications, and integrity checks
- Tests in `tests/epub/`, `tests/translation/`, `tests/glossary/`, `tests/summaries/`, `tests/idioms/`, `tests/graph/`, and `tests/packets/` passing (64 total).
- `docs/30-operations/repo-map.md` updated for M9 layout.
- `docs/30-operations/artifact-paths.md` already includes `pass3.json` and `chapter.json`.
- `IMPLEMENTATION_PLAN.md` M9 checklist updated to complete.

Verified commands from the previous session:

- `uv run --extra dev ruff check src\resemantica tests\translation`
- `uv run --extra dev mypy src\resemantica`
- `uv run --extra dev pytest tests\epub tests\translation tests\glossary tests\summaries tests\idioms tests\graph tests\packets` (64 passed)

## Working Tree State (Not Committed Yet)

Current local changes:

- `IMPLEMENTATION_PLAN.md`
- `docs/30-operations/artifact-paths.md`
- `docs/30-operations/handover-next-session.md`
- `docs/30-operations/repo-map.md`
- `src/resemantica/cli.py`
- `src/resemantica/settings.py`
- `src/resemantica/db/migrations/007_packets.sql`
- `src/resemantica/db/packet_repo.py`
- `src/resemantica/llm/tokens.py`
- `src/resemantica/llm/prompts/translate_pass3.txt`
- `src/resemantica/packets/` (new package)
- `src/resemantica/translation/pass3.py`
- `src/resemantica/translation/risk.py`
- `src/resemantica/translation/pipeline.py`
- `src/resemantica/translation/validators.py`
- `tests/packets/` (new test suite)
- `tests/translation/test_pass3_and_risk.py`

No push has been performed.

## Runtime Test Note

- llama.cpp server is currently available at: `http://127.0.0.1:8033`
- If running live translation tests, point `llm.base_url` to this endpoint (default config currently uses `http://localhost:8080`).
- Live EPUB fixture available at: `tests/test_epub_src/Test_ebook.epub`
- If this fixture is used for live EPUB smoke tests, clean generated `artifacts/releases/<release_id>/` outputs after testing.
- `tests/test_epub_src/` is local-only and must not be pushed to remote.

## Next Objective

Start **M10** only:

- Task brief: `docs/40-tasks/task-10-orchestration.md`
- LLD: `docs/20-lld/lld-10-orchestration.md`

## Existing M9 Files (orientation)

- `src/resemantica/translation/pass3.py`
- `src/resemantica/translation/risk.py`
- `src/resemantica/translation/validators.py`
- `src/resemantica/translation/pipeline.py`
- `src/resemantica/llm/prompts/translate_pass3.txt`
- `tests/translation/test_pass3_and_risk.py`
- `tests/translation/test_translate_chapter.py`

---
