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
- Cache corruption or parse failure is treated as cache miss, not as successful reuse.

## Tests

- Batched mode calls pass1 for all chapters before any pass2 call.
- Existing `translate-chapter` remains pass1 -> pass2 -> pass3 for one chapter.
- Cache hit avoids model call.
- Cache miss calls model and records cache metadata.
- Invalid cached payload is ignored and regenerated.

## Out Of Scope

- Parallel LLM calls.
- Prompt template rewrites.
- Changing validation rules.

## Implementation Notes

- `translate-range` supports opt-in `--batched-model-order`; the default remains per-chapter pass order.
- Batched orchestration reuses the existing `translate_chapter_pass1/2/3` functions and persists pass progress in run state.
- Preprocessing LLM output cache entries are JSON artifacts under `releases/{release_id}/cache/llm`.
- Cached raw outputs are parsed through the same validation path as fresh model outputs; invalid cached payloads are regenerated.
