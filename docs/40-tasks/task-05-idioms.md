# Task 05: Idioms Workflow

- **Milestone:** M5
- **Depends on:** M1, M3
- **Status:** Completed on 2026-04-28 (implementation + validation complete)
- **Post-MVP Improvements:** 2026-05-03

## Goal

Implement idiom detection, normalization, storage, and exact-match retrieval for packet assembly.

## Scope

In:

- idiom detection from extracted chapter text
- idiom policy model and SQLite repository
- deterministic normalization and duplicate detection
- exact-match retrieval by source text
- human-override review workflow
- unique constraint on idiom_candidates to prevent cross-chapter duplicates

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

## Post-MVP Improvements (2026-05-03)

Three categories of quality-of-life improvements applied after initial M5 completion:

### 1. Detect Prompt Improvement (`llm/prompts/idiom_detect.txt`)

- Added explicit instruction that `source_text` must be the idiom phrase only (e.g. `"孤苦伶仃"`, NOT `"有位孤苦伶仃的清瘦少年"`)
- Added concrete negative examples of what to exclude (dates, common expressions)
- Bumped prompt version to v2.0 (invalidates LLM response cache)

### 2. Translation Reliability

- Restructured `idiom_translate.txt` to CONTEXT-first pattern (same as glossary)
- Added response post-processing in `translate_idiom_candidates()` to strip label prefixes and chain-of-thought leftovers
- Bumped `idiom_translate.txt` to v2.0

### 3. Human Override Workflow

- New CLI command: `preprocess idiom-review` — dumps translated candidates to a human-editable JSON review file
- Modified `preprocess idiom-promote --review-file PATH` — reads edited file, applies overrides, deletions, and additions, then runs standard validation + promotion
- Review file uses `review_schema_version` field for forward compatibility

### 4. Cross-Chapter Deduplication

- Added `UNIQUE (release_id, normalized_source_text)` constraint to `idiom_candidates` table
- Changed upsert from `ON CONFLICT(candidate_id)` to `ON CONFLICT(release_id, normalized_source_text)` with merge logic (sums appearance_count, merges chapter ranges)
- Prevents duplicate rows when the same idiom is detected across multiple chapters
