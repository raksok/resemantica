# Handover Prompt: Resemantica (Post-M1)

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

M1 (`task-01-epub-roundtrip`) is implemented and validated.

Completed and verified:

- EPUB unpack + OPF/spine discovery + deterministic rebuild.
- XHTML parsing and block extraction with stable IDs/order.
- Placeholder extraction/restoration with nested-map fields:
  - `parent_placeholder`
  - `closing_order`
- Segment splitting with `_seg{NN}` IDs and `parent_block_id`.
- CLI command: `epub-roundtrip`.
- Tests in `tests/epub/` passing.
- `docs/30-operations/repo-map.md` updated for real package layout.

Verified commands from the previous session:

- `uv run --extra dev ruff check src\resemantica tests\epub docs\30-operations\repo-map.md`
- `uv run --extra dev mypy src\resemantica`
- `uv run --extra dev pytest tests\epub` (8 passed)
- `uv run python -m resemantica.cli epub-roundtrip --input artifacts\smoke_fixture.epub --release smoke-m1`

## Important Current Gap

- In `IMPLEMENTATION_PLAN.md`, M1 action item for `logging_config.py` is still unchecked.

## Next Objective

Start **M2** only:

- Task brief: `docs/40-tasks/task-02-single-chapter-translation.md`
- LLD: `docs/20-lld/lld-02-single-chapter-translation.md`

Focus for M2:

1. Single-chapter translation flow using M1 extraction outputs.
2. Pass 1 + Pass 2 implementation with placeholder safety.
3. Structural validation and failure behavior.
4. `translate-chapter` CLI wiring.
5. Artifact/checkpoint persistence for resumability.
6. Tests for placeholder-preserving translation and hard-failure paths.

## Files Added in M1 (for orientation)

- `src/resemantica/cli.py`
- `src/resemantica/settings.py`
- `src/resemantica/epub/` (extractor, parser, placeholders, validators, rebuild, models)
- `src/resemantica/db/sqlite.py`
- `src/resemantica/db/migrations/001_initial.sql`
- `tests/epub/test_roundtrip.py`
- `tests/epub/test_placeholders.py`

---

