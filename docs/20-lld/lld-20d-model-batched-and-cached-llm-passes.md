# LLD 20d: Model-Batched And Cached LLM Passes

## Summary

Reduce model swapping by batching compatible LLM work by model and reuse cached deterministic extraction outputs where source hash and prompt identity match.

## Problem Statement

`translate-range` currently executes pass1, pass2, and pass3 per chapter. With separate translator and analyst models, this can repeatedly switch loaded models on local inference backends. Preprocessing stages also rerun model extraction work that could be reused when source hashes, model names, and prompt versions are unchanged.

## Technical Design

### Batched Translation Range

Add an opt-in model-batched path:

```text
for chapter in range: pass1 translator
for chapter in range: pass2 analyst
for chapter in range: pass3 analyst
```

This path must reuse existing `translate_chapter_pass1/2/3` functions and checkpoints. It changes orchestration order only, not pass internals.

When `[batch_order].enabled` is true and the selected range is larger than `batch_order.translation_chunk_size`, batched translation runs the same pass order per chunk:

```text
for chapter in chunk 1: pass1 translator
for chapter in chunk 1: pass2 analyst
for chapter in chunk 1: pass3 analyst
for chapter in chunk 2: pass1 translator
...
```

The chunk checkpoint is marked completed only after pass3 finishes for the chunk.

Configuration/CLI decision:

- Add a conservative option such as `--batched-model-order` for `translate-range` and production range execution, unless implementation chooses config-only control.
- Default remains existing per-chapter order for compatibility unless explicitly changed in the implementation task.

### Extraction Cache

Add cache identity for preprocessing LLM outputs:

```text
release_id
chapter_number
source_hash
stage_name
chunk_index
model_name
prompt_version
prompt_hash
schema_version
```

Cache may be represented as JSON artifacts plus SQLite metadata. Cached payloads must be parsed and validated through the same code path as fresh model output.

## Failure Behavior

- If pass1 succeeds for all chapters and pass2 fails at one chapter, previously generated pass1 artifacts remain valid checkpoints.
- Batched mode records per-pass progress in run state.
- Chunked batched mode also records `chunk_checkpoints` for cleanup boundaries.
- Cache corruption or parse failure is treated as cache miss, not as successful reuse. Translation checkpoint reuse follows the same rule for Pass 1, Pass 2, and Pass 3, while required upstream pass artifacts remain strict inputs.
- Shared JSON artifacts are serialized before a flushed same-directory temporary write and atomically replace their destination. An interrupted update therefore leaves either the previous valid artifact or no destination, both of which are safe to resume.
- Batched pass-level exception handlers emit `translate-chapter.pass1.failed`, `translate-chapter.pass2.failed`, or `translate-chapter.pass3.failed` with severity `error`, `chapter_number`, `pass_name`, and `reason` before recording the failure in the range checkpoint.

## Resume After Stop

`_translate_range_batched` consumes the run-state checkpoint on re-run to skip already-completed chapters in each pass:

1. `run_stage` loads the prior run state from the tracking DB.
2. The checkpoint's `pass1_completed` / `pass2_completed` / `pass3_completed` lists are pre-populated into the batched loop.
3. Each loop skips chapters already recorded in the corresponding completed list from the prior run.
4. Chapters that are NOT in the completed list get processed; old failures are NOT carried over (they are re-attempted fresh).

This avoids re-iterating completed chapters through the per-pass checkpoint lookup, and makes the progress bar reflect only unprocessed work.

For chunked batched mode, completed chunks are skipped on resume. Incomplete chunks continue to use `pass1_completed`, `pass2_completed`, and `pass3_completed` from run state.

## Tests

- Batched mode calls pass1 for all chapters before any pass2 call.
- Chunked batched mode calls pass1/pass2/pass3 for one chunk before starting the next chunk.
- Existing `translate-chapter` remains pass1 -> pass2 -> pass3 for one chapter.
- Cache hit avoids model call.
- Cache miss calls model and records cache metadata.
- Invalid cached payload is ignored and regenerated.
- Batched pass1/pass2/pass3 exceptions emit the matching `translate-chapter.passN.failed` event.

## Out Of Scope

- Parallel LLM calls.
- Prompt template rewrites.
- Changing validation rules.

## Implementation Notes

- `translate-range` supports opt-in `--batched-model-order`; the default remains per-chapter pass order.
- Batched orchestration reuses the existing `translate_chapter_pass1/2/3` functions and persists pass progress in run state.
- Preprocessing LLM output cache entries are JSON artifacts under `releases/{release_id}/cache/llm`.
- Cached raw outputs are parsed through the same validation path as fresh model outputs; invalid cached payloads are regenerated.
