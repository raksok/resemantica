# Handover Prompt: Resemantica (Post-M8)

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

M1, M2, M3, M4, M5, M6, M7, and M8 are implemented and validated.

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
- Tests in `tests/epub/`, `tests/translation/`, `tests/glossary/`, `tests/summaries/`, `tests/idioms/`, `tests/graph/`, and `tests/packets/` passing.
- `docs/30-operations/repo-map.md` updated for M8 layout.
- `docs/30-operations/artifact-paths.md` updated for packet + bundle artifact naming.
- `IMPLEMENTATION_PLAN.md` M8 checklist updated to complete.

Verified commands from the previous session:

- `uv run --extra dev ruff check src\resemantica tests\packets docs\30-operations\repo-map.md`
- `uv run --extra dev mypy src\resemantica`
- `uv run --extra dev pytest tests\packets tests\graph tests\idioms tests\summaries tests\glossary tests\translation tests\epub` (40 passed)
- `uv run python -m resemantica.cli --help` (includes `packets`)
- `uv run python -m resemantica.cli packets --help`
- `uv run python -m resemantica.cli packets build --help`

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
- `src/resemantica/packets/` (new package)
- `tests/packets/` (new test suite)

No push has been performed.

## Runtime Test Note

- llama.cpp server is currently available at: `http://127.0.0.1:8033`
- If running live translation tests, point `llm.base_url` to this endpoint (default config currently uses `http://localhost:8080`).
- Live EPUB fixture available at: `tests/test_epub_src/Test_ebook.epub`
- If this fixture is used for live EPUB smoke tests, clean generated `artifacts/releases/<release_id>/` outputs after testing.
- `tests/test_epub_src/` is local-only and must not be pushed to remote.

## Next Objective

Start **M9** only:

- Task brief: `docs/40-tasks/task-09-pass3-and-risk.md`
- LLD: `docs/20-lld/lld-09-pass3-and-risk.md`

Focus for M9:

1. Implement `translation.pass3.translate_pass3()` readability polish with strict fidelity/terminology guardrails.
2. Implement deterministic risk classifier (`translation.risk.classify_paragraph_risk()`) using the D21 weighted formula and persisted sub-scores.
3. Enforce high-risk skip behavior (`risk >= 0.7`) so final output remains validated Pass 2 output for high-risk paragraphs.
4. Add Pass 3 integrity validator (`translation.validators.validate_pass3_integrity()`) to catch terminology drift and meaning drift.
5. Persist Pass 3 artifacts + risk reports and include pass decisions in chapter validation outputs.
6. Add tests in `tests/translation/` for risk skip behavior, deterministic scoring, threshold edge at `0.7`, integrity fallback, and chapter-level failure behavior.

## Existing M8 Files (orientation)

- `src/resemantica/packets/` (`models.py`, `builder.py`, `bundler.py`, `invalidation.py`)
- `src/resemantica/db/packet_repo.py`
- `src/resemantica/db/migrations/007_packets.sql`
- `src/resemantica/llm/tokens.py`
- `tests/packets/test_packet_pipeline.py`

---

