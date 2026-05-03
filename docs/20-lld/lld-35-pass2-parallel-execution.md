# LLD 35: Pass 2 Parallel Execution

## Summary

Replace the sequential for-loop in `translate_chapter_pass2()` with a `ThreadPoolExecutor` so independent blocks are processed concurrently, reducing wall-clock time proportionally to `pass2_concurrency`.

## Problem Statement

`translate_chapter_pass2()` iterates over all pass1 blocks one by one, calling `translate_pass2()` → LLM → parse → validate for each. With 100+ blocks per chapter and 1-3s per LLM call, this adds significant latency. Since each block's pass2 evaluation is completely independent (no cross-block dependencies), the loop is embarrassingly parallel.

The existing `LLMClient` is synchronous (OpenAI-compatible via httpx) — switching to async would be invasive. `ThreadPoolExecutor` provides parallel execution with minimal code change and zero quality impact (same prompt, same model, same per-block logic).

## Design

### 1. Config Addition

`TranslationConfig` gains `pass2_concurrency: int = 2`, read from `[translation]` TOML:

```toml
[translation]
pass2_concurrency = 3
```

Validation in `validate_config()`: must be >= 1.

### 2. Per-Block Extraction

The for-loop body in `translate_chapter_pass2()` is extracted into a standalone function:

```python
def _process_pass2_block(
    block: dict[str, Any],
    *,
    pass2_prompt_template: str,
    analyst_model: str,
    client: LLMClient,
    placeholders_by_block: dict[str, list[PlaceholderEntry]],
    release_id: str,
    run_id: str,
    chapter_number: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Process one pass2 block. Returns (block_result, structure_checks, fidelity_check)."""
```

- For **normal blocks** (single segment): calls `translate_pass2()` once, validates structure, restores placeholders, validates fidelity. Returns one structure check and one fidelity check.
- For **resegmented blocks** (was_resegmented=true): iterates segments sequentially (they depend on `prior_segment_translations`), validates each segment's structure, joins segments, restores placeholders, validates fidelity. Returns multiple structure checks (one per segment) and one fidelity check.
- Emits `paragraph_completed` / `paragraph_skipped` events via the existing thread-safe `_emit_translation_event` helper.

### 3. Parallel Orchestration

```python
concurrency = config.translation.pass2_concurrency
blocks_to_process = [
    b for b in pass1_payload.get("blocks", [])
    if b.get("status") != "failed"
]

with ThreadPoolExecutor(max_workers=concurrency) as executor:
    fut_map: dict[Future, int] = {}
    for i, block in enumerate(blocks_to_process):
        fut = executor.submit(
            _process_pass2_block,
            block,
            pass2_prompt_template=pass2_prompt.template,
            analyst_model=analyst_model,
            client=client,
            placeholders_by_block=placeholders_by_block,
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
        )
        fut_map[fut] = i

    results: dict[int, tuple] = {}
    for future in as_completed(fut_map):
        idx = fut_map[future]
        results[idx] = future.result()  # may raise

# Reconstruct in original order:
for idx in sorted(results):
    block_result, struct_checks, fidelity_check = results[idx]
    pass2_blocks.append(block_result)
    pass2_structure_checks.extend(struct_checks)
    fidelity_checks.append(fidelity_check)
```

### 4. Failed Pass1 Blocks

Blocks where `block["status"] == "failed"` are filtered before the thread pool and emit `paragraph_skipped` events (same as current behavior, no LLM call needed).

### 5. Error Propagation

If any `future.result()` raises (e.g. `RuntimeError` from structure validation failure in a parallel task), the exception propagates out of the `with` block. The executor's `__exit__` waits for all submitted tasks to finish before re-raising (via `shutdown(wait=True)`). This means on failure, some tokens may be "wasted" on tasks that completed after the failure — acceptable since failures are rare, and the alternative (batch-submit + early break) adds complexity for marginal gain.

### 6. Post-Processing (unchanged)

After the parallel section, the code proceeds exactly as before: writes `pass2_artifact.json`, save checkpoint, write validation reports, check for structural/fidelity failures.

## Thread Safety Notes

| Resource | Status |
|---|---|
| `LLMClient.generate_text()` | Safe — httpx connection pool is thread-safe |
| `LLMClient._openai_client` lazy init | Race possible but benign (both threads create a valid client, one gets stored) |
| Usage counters (`llm_request_count`, etc.) | Not synchronized — minor inaccuracy under concurrent access |
| `_emit_translation_event()` | Safe — wraps entire body in try/except |
| `placeholders_by_block` dict | Read-only after construction |
| Per-block results dict | Each thread builds its own, returned after join |

## Backward Compatibility

| Scenario | Behaviour |
|---|---|
| `pass2_concurrency=1` | Behaves identically to current sequential code |
| Config omits `pass2_concurrency` | Defaults to 2 in code |
| Zero or negative value | `validate_config()` raises `ValueError` |
| Existing checkpoints | Unchanged — checkpoint save/load logic is untouched |

## Edge Cases

- **Single block chapter:** No parallelism (only 1 task in the pool), works correctly.
- **Resegmented block:** Treated as one atomic task. Internal segments still sequential within that task.
- **All blocks failed pass1:** Thread pool receives zero tasks, emits no events, returns empty results.
- **Analyst model OOM under concurrent load:** `pass2_concurrency` tunes this directly — reduce to 1 if needed.

## Out Of Scope

- Async `LLMClient` — would benefit all passes but is a larger refactor.
- Rate limiting / TPM-aware scheduling — `pass2_concurrency` is a static cap.
- Parallelizing Pass 1 or Pass 3 — each has different constraints.
