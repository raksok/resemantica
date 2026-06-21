# LLD 69: Continuity Batch-Order Chunking

## Summary

`preprocess-continuity` uses batch-order chunks when `batch_order.enabled = true`
and the selected chapter count is greater than
`batch_order.summary_chunk_multiplier * summaries.chapter_concurrency`.

Within each chunk, Chinese graph continuity refresh runs first in chapter order.
English graph compact derivation then runs for all completed Chinese rows in that
chunk using `summaries.chapter_concurrency` workers.

## Behavior

For each active chunk:

1. Build graph continuity input for each chapter in order.
2. Reuse an existing approved `story_so_far_zh_graph_compact` row only when
   resume is enabled, chunking is active, force is false, and
   `derived_from_chapter_hash` matches the current continuity input source hash.
3. Regenerate stale or missing Chinese graph compact rows with the analyst model.
4. Backfill missing or stale `story_so_far_en_graph_compact` rows from current
   approved Chinese graph compact rows with the translator model.
5. Write per-chapter graph continuity artifacts after English rows are current.
6. Mark the chunk completed only after all expected rows and artifacts are
   current.

`force=True` ignores chunk checkpoints and regenerates the selected range.

## Resume

A completed chunk is skipped only when:

- the checkpoint status is `completed`
- checkpoint `chapter_start` and `chapter_end` match the current chunk
- checkpoint metadata `last_good_chapter` covers the chunk end
- expected Chinese graph compact rows match the current continuity source hash
- expected English rows point at the current Chinese row and glossary hash
- expected graph continuity artifacts exist

Incomplete chunks resume from durable rows. Current Chinese rows are reused when
their source hash matches; missing or stale English rows are translated without
rerunning the analyst model.

`run retry-failed --stage preprocess-continuity` uses failed continuity chunk
checkpoints as retry boundaries. If a chunk fails after writing some Chinese
rows but before English derivation and artifacts, the retry unit starts at the
failed chunk start so English/artifact backfill for earlier chapters in that
chunk is not skipped.

## Events

Chunked continuity emits:

- `preprocess-continuity.chunk_started`
- `preprocess-continuity.chunk_completed`
- `preprocess-continuity.chunk_failed`
- `preprocess-continuity.graph_compact.retry`

Chunk events include `chunk_index`, `chunk_count`, `chapter_start`,
`chapter_end`, `chunk_size`, and `last_good_chapter`.

## Scope

This milestone does not add continuity support to
`run cleanup --scope last-good-chunk`. That cleanup scope remains limited to
`preprocess-summaries` and `translate-range`.
