# LLD 84: Range-Safe Translation Recovery

## Summary

Batched translation may reuse a completed chunk checkpoint only when its stored chapter bounds cover the current chunk and every requested chapter has complete final translation artifacts. A narrower retry range must not reinterpret or overwrite a chunk index that was created for a different range.

EPUB reconstruction performs the same final-translation audit as its orchestration gate before mutating reconstruction outputs. Direct CLI and TUI rebuild entry points always enforce orchestration gates.

## Chunk Compatibility

`chunk_checkpoints` keeps its existing primary key and schema. The stored `chapter_start` and `chapter_end` are part of the checkpoint's runtime identity:

- Reuse is allowed when `stored_start <= requested_start` and `stored_end >= requested_end`.
- A completed compatible row is skipped only when the requested chapters also pass the translation completeness audit.
- An exact range may replace its row.
- A requested range that contains the stored range may safely widen and replace its row.
- A narrower, shifted, disjoint, or partially overlapping requested range runs normally but must not replace the incompatible row at that chunk index.
- `--force` bypasses reuse but does not permit an incompatible checkpoint overwrite.

Pass checkpoints and artifacts remain the authoritative per-chapter recovery state. Chunk rows remain progress and cleanup boundaries; `chunk_index` alone is never proof that the current chapter scope is complete.

## Rebuild Preflight

Before deleting, copying, or creating reconstruction work output, rebuild must:

1. Load the extracted chapter manifest and non-story classification.
2. Require the placeholder map for every chapter that will be rebuilt.
3. Audit every extracted parent block against non-empty Pass 2/3 final output.
4. Permit an untranslated non-story chapter only when it has no Pass 2/3 artifact.
5. Emit `epub-rebuild.preflight_failed` and stop if any chapter is incomplete.

A failed preflight preserves the existing reconstruction work tree and final EPUB. The CLI and TUI reconstruction paths set `enforce_gates=True`; callers cannot bypass the direct reconstruction-input gate through those interfaces. Historical preprocess, summary, graph, and packet state is not a reconstruction dependency once final translations exist.

## Compatibility

No database migration, CLI flag, configuration field, prompt version, or artifact schema changes. Existing rows become safer because their stored bounds and on-disk artifacts are validated before reuse.

## Tests

- Exact and covering chunk ranges are reusable.
- Shifted chunk indices execute and do not overwrite the older checkpoint range.
- A completed checkpoint with incomplete artifacts executes again.
- Failed rebuild preflight preserves existing outputs.
- CLI and TUI rebuild dispatch enforce gates.
- Retry discovery treats a successful checkpoint with an incomplete artifact as retryable.
