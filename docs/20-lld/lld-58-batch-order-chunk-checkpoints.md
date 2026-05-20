# LLD 58: Batch-Order Chunk Checkpoints

## Summary

Long batch-order runs are split into durable chunks. A chunk runs the full model-order loop before the next chunk begins, which limits crash recovery and cleanup to the last incomplete chunk.

## Configuration

```toml
[batch_order]
enabled = true
summary_chunk_multiplier = 10
translation_chunk_size = 10
```

Summary chunk size is `summary_chunk_multiplier * summaries.chapter_concurrency`. Summary chunking activates only when the selected chapter count is larger than that effective size. Translation chunking activates only for batched `translate-range` runs larger than `translation_chunk_size`.

## Storage

`chunk_checkpoints` records:

- `release_id`
- `run_id`
- `stage_name`
- `chunk_index`
- `chapter_start`
- `chapter_end`
- `status`
- `metadata_json`

The last `status = 'completed'` row for a stage is the cleanup boundary.

## Summary Execution

For each active summary chunk:

1. Run Chinese structured generation and LLM validation for the chunk.
2. Advance `zh_last_chapter` as soon as contiguous Chinese results complete.
3. Assemble ordered Chinese story and compact rows. If a compact row exceeds `summaries.story_compact_max_tokens`, the summary compaction helper repairs the over-budget draft before the chunk fails; only an under-budget compact result is cached or saved.
4. Run English derivation for the chunk.
5. Advance `en_last_chapter` as contiguous English results complete.
6. Mark the chunk completed only after English artifacts and checkpoints are written.

Completed summary chunks are skipped on resume only when their stored `chapter_start`/`chapter_end` match the current chunk and their metadata `last_good_chapter` is at least the chunk's `chapter_end`. Incomplete chunks, stale completed chunks whose English checkpoint still lags the chunk end, and completed rows from a different chapter scope resume from `summary_checkpoints`. If `story_last_chapter` is ahead of `en_last_chapter`, the summary pipeline creates English-only backfill jobs from approved Chinese short and compact rows and advances through persisted English rows after the gap is filled.

## Batched Translation Execution

For each active translation chunk:

1. Run pass1 for all chapters in the chunk.
2. Run pass2 for chapters with completed pass1 in the chunk.
3. Run pass3 for chapters with completed pass2 in the chunk.
4. Mark the chunk completed after pass3 finishes for the chunk.

Existing pass checkpoints and run-state pass lists remain the normal resume authority; chunk checkpoints provide cleanup boundaries.

## Cleanup

`last-good-chunk` resolves the stage from tracking run state or `--stage`.

- For `preprocess-summaries`, cleanup removes summary and downstream rows/artifacts after the last completed chunk and rewinds `summary_checkpoints` to `last_good_chapter`.
- For `translate-range`, cleanup removes translation rows/artifacts after the last completed chunk and trims run-state pass lists to the boundary.
- Broad cleanup scopes (`run`, `preprocess`, `keep-extracted`, and `all`) delete summary chunk checkpoints outright so summary reruns restart from the remaining extracted chapter input. Only `last-good-chunk` rewinds to a completed chunk boundary.

## Events

Chunk events include `chunk_index`, `chunk_count`, `chapter_start`, `chapter_end`, `chunk_size`, and `last_good_chapter`. For summary chunks, `last_good_chapter` is the current English phase checkpoint and determines whether a completed chunk can be skipped on resume.
