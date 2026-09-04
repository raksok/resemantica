# Task 85: Rebuild Direct-Input Gate

## Milestone

M85

## Depends On

M84

## Goal

Allow EPUB reconstruction when its direct inputs are complete, without requiring historical preprocessing artifacts that reconstruction does not consume.

## Scope

- Specialize the `epub-rebuild` orchestration gate to extracted inputs, non-story classification, placeholder maps, and final Pass 2/3 completeness.
- Keep unresolved-vote, summary, graph, and packet checks unchanged for their consuming stages.
- Align unclassified and non-story chapter handling with rebuild preflight.
- Update gate regression tests and operator documentation.

## Owned Files Or Modules

- `src/resemantica/orchestration/gates.py`
- `tests/orchestration/test_gates.py`
- Gate, reconstruction, task, and troubleshooting documentation

## Interfaces To Satisfy

- Existing CLI syntax, configuration, schemas, and events remain unchanged.
- Unclassified chapters are translation-required.
- Only explicitly non-story chapters without Pass 2/3 artifacts may be skipped.
- Direct rebuild and TUI reconstruction continue to enforce the narrowed gate.

## Tests Or Smoke Checks

- `uv run --extra dev pytest tests\orchestration\test_gates.py tests\epub tests\cli tests\tui -q`
- `uv run --extra dev ruff check src\resemantica tests`
- `uv run --extra dev ruff format --check src\resemantica\orchestration\gates.py tests\orchestration\test_gates.py`
- `uv run --extra dev mypy src\resemantica`
- `uv run --extra dev pytest tests -q`
- `git diff --check`
- Read-only pilot `check_stage_gate(stage_name="epub-rebuild", release_id="1", run_id="001")`

## Done Criteria

- The pilot rebuild gate reports success when final translation artifacts are complete.
- Stale glossary votes and missing legacy summary artifacts no longer trigger rebuild review generation.
- Direct reconstruction input failures remain hard failures before filesystem mutation.
