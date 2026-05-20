# Task 58: Batch-Order Chunk Checkpoints

## Milestone

M58

## Depends On

M57

## Goal

Make long batch-order summary and translation runs crash-recoverable at chunk boundaries. A chunk completes the full model-order loop before the next chunk starts, and durable chunk checkpoints identify the last cleanup-safe chapter.

## Scope

- Add `[batch_order]` config for summary and translation chunk sizing.
- Add `chunk_checkpoints` storage and repository helpers.
- Run `preprocess-summaries` in chunk order for large ranges: Chinese generation and validation, ordered story assembly, then English derivation.
- Preserve compact-summary budget recovery inside ordered story assembly: over-budget compact drafts are repaired before chunk failure and only valid compact rows can complete a chunk.
- Run batched `translate-range` in chunk order for large ranges: pass1, pass2, pass3 per chunk.
- Add `last-good-chunk` cleanup planning/apply behavior for summaries and translation.
- Document resume, cleanup, and event payload behavior.

## Interfaces

- Config: `batch_order.enabled`, `batch_order.summary_chunk_multiplier`, `batch_order.translation_chunk_size`.
- Events: `preprocess-summaries.chunk_started/completed/failed` and `translate-range.chunk_started/completed/failed`.
- Cleanup: `run cleanup-plan/apply --scope last-good-chunk [--stage preprocess-summaries|translate-range]`.

## Tests

- Settings parsing and validation.
- SQLite schema and chunk checkpoint repository behavior.
- Chunked batched translation ordering and resume.
- CLI cleanup parsing.
- Last-good-chunk cleanup planning/apply for summaries and translation.

## Done Criteria

- Large ranges advance by completed chunks.
- Per-phase checkpoints still advance at contiguous chapter granularity.
- Cleanup rewinds to the last completed chunk and removes later artifacts/rows.
- Focused suites for summaries, orchestration, translation, CLI, and DB pass.
