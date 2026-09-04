# Task 83: Crash-Safe JSON Checkpoints

## Milestone

M83

## Depends On

M82

## Goal

Recover automatically when a power interruption leaves a translation checkpoint artifact unreadable, and prevent future shared JSON writes from exposing partial destination files.

## Scope

- Write shared JSON artifacts through a flushed same-directory temporary file and atomic replacement.
- Preserve an existing artifact if serialization, writing, synchronization, or replacement fails.
- Treat unreadable Pass 1, Pass 2, and Pass 3 checkpoint artifacts as cache misses.
- Keep required upstream translation artifacts strict and retain semantic Pass 2 cache validation.
- Document outage diagnosis and retry behavior.

## Owned Files Or Modules

- `src/resemantica/utils.py`
- `src/resemantica/translation/pipeline.py`
- Shared utility and translation regression tests
- Translation cache and troubleshooting documentation

## Interfaces To Satisfy

- Existing CLI commands and `--force` behavior remain unchanged.
- Database schemas, checkpoint keys, prompts, generic event shape, and JSON artifact shapes remain unchanged; recovery emits a pass-specific `cache_invalid` warning event.
- A normal `run retry-failed` invocation regenerates an unreadable failed-pass cache without manual deletion.

## Tests Or Smoke Checks

- `uv run --extra dev pytest tests\test_utils.py tests\translation tests\orchestration -q`
- `uv run --extra dev ruff check src\resemantica tests`
- `uv run --extra dev mypy src\resemantica`
- `git diff --check`

## Done Criteria

- Interrupted writes cannot replace a valid artifact with partial JSON.
- NUL-filled translation cache artifacts no longer cause repeated `JSONDecodeError` failures.
- The affected pass regenerates and records a valid successful artifact without force.
- Existing cache reuse and validation behavior remains passing.
