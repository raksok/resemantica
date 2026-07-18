# Task 77: Warning Quality And Tracking Write Serialization

## Milestone

M77

## Depends On

M76

## Goal

Keep operator warnings actionable and prevent in-process SQLite contention from dropping tracking events.

## Scope

- Report expected disabled, stale-rebuild, non-story, and empty-frontmatter events at info level.
- Report unresolved candidates at debug level with one warning summary when unresolved items remain.
- Remove duplicate direct warnings where a structured event is emitted.
- Serialize in-process tracking writes while retaining bounded cross-process lock retries.

## Owned Files Or Modules

- `src/resemantica/glossary`
- `src/resemantica/idioms`
- `src/resemantica/packets`
- `src/resemantica/tracking`
- logging and event tests

## Interfaces To Satisfy

- Missing prerequisites, exhausted retries, and incomplete artifacts remain warning or error events.
- Tracking schema and cross-process retry bounds remain unchanged.
- Canonical chapter numbering is not rewritten.

## Tests Or Smoke Checks

- `uv run --extra dev pytest tests\glossary tests\idioms tests\packets tests\tracking -q`
- `uv run --extra dev pytest tests\orchestration\test_logging_contract.py -q`

## Done Criteria

- Expected control-flow events no longer inflate warning counts.
- Candidate-level unresolved events are debug-only and summary warnings are deduplicated.
- Concurrent in-process event emission persists every event.
