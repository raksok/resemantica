# Task 69: Continuity Batch-Order Chunking

## Milestone

M69

## Depends On

M68

## Goal

Reduce analyst/translator model switching in `preprocess-continuity` while
preserving chapter-order Chinese continuity dependencies.

## Scope

- Split chunked continuity into ordered Chinese graph compact generation followed
  by chunk-level English graph compact derivation.
- Reuse existing `chunk_checkpoints` for continuity resume boundaries.
- Reuse current approved Chinese graph compact rows in incomplete chunks when
  their continuity source hash matches.
- Backfill missing or stale English graph compact rows without rerunning the
  analyst model.
- Keep invalid graph continuity cache recovery behavior unchanged.
- Retry fresh invalid graph continuity output without caching failed attempts.
- Plan failed continuity retries from failed chunk boundaries so English rows
  and artifacts inside a failed chunk are backfilled.
- Leave last-good-chunk cleanup support for continuity out of scope.

## Owned Files Or Modules

- `src/resemantica/summaries/continuity.py`
- `src/resemantica/orchestration/runner.py`
- `tests/summaries/test_graph_continuity_refresh.py`
- Continuity and chunk checkpoint LLD/task documentation

## Interfaces

Python:

- `summaries.continuity.preprocess_continuity(..., resume: bool = True, force: bool = False)`

CLI behavior is unchanged. `OrchestrationRunner` passes `resume=not force`.

## Tests

- Chunked continuity model order is analyst for all chunk chapters, then
  translator for all chunk chapters.
- Completed chunk resume skips only when checkpoint, rows, and artifacts are
  complete.
- English-only backfill uses current approved graph compact rows without analyst
  calls.
- Stale graph compact rows regenerate when the current source hash differs.
- Chunk failure records a `chunk_failed` event and failed checkpoint.
- Fresh invalid graph compact output retries and only valid output is cached.
- Retry-failed continuity planning includes failed chunk ranges plus missing
  English graph compact rows or artifacts.

## Done Criteria

- Chunked `preprocess-continuity` reduces model switching within each chunk.
- Resume and backfill preserve chapter-order Chinese dependencies.
- Existing invalid-cache recovery behavior remains covered and passing.
- Fresh invalid model output is retried, but invalid output remains uncached.
- Targeted tests and Ruff checks pass.
