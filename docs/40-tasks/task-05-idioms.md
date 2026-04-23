# Task 05: Idioms Workflow

- **Milestone:** M5
- **Depends on:** M1, M3

## Goal

Implement idiom detection, normalization, storage, and exact-match retrieval for packet assembly.

## Scope

In:

- idiom detection from extracted chapter text
- idiom policy model and SQLite repository
- deterministic normalization and duplicate detection
- exact-match retrieval by source text

Out:

- packet assembly itself
- translation-time fuzzy idiom matching
- graph storage for idioms

## Owned Files Or Modules

- `src/resemantica/idioms/`
- `src/resemantica/db/`
- `tests/idioms/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-05-idioms.md`
- data contract: idiom policy store in `../../DATA_CONTRACT.md`
- CLI: `uv run python -m resemantica.cli preprocess idioms`

## Tests Or Smoke Checks

- idiom extraction from representative Chinese text using a mocked analyst model
- duplicate detection from normalized source text
- SQLite storage and retrieval
- exact-match retrieval for packet assembly

## Done Criteria

- idioms can be extracted from a chapter and stored in SQLite
- duplicate idioms are merged or rejected deterministically
- approved idiom policies are available by exact source-text match
- model output does not write directly to authority state without validation
