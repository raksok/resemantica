# Task 35: Pass 2 Parallel Execution

## Goal

Speed up Pass 2 by processing independent blocks concurrently via `ThreadPoolExecutor`, reducing wall-clock time by ~N× for `pass2_concurrency=N`.

## Scope

In:

- Add `pass2_concurrency` (int, default 2) to `TranslationConfig` in `settings.py`, read from `[translation]` TOML section.
- Add `pass2_concurrency` to `resemantica.toml` and `resemantica-pilot.toml`.
- Refactor the per-block loop in `translate_chapter_pass2()` to submit independent blocks to a `ThreadPoolExecutor` and collect results.
- Preserve all existing validation, fidelity checks, placeholder restoration, and event emission inside each parallel task.
- Preserve original block ordering in the output artifact (sort by original index after parallel completion).

Out:

- Changing `translate_pass2()`, the prompt file, or pass2's return signature.
- Parallelizing segments within a resegmented block (they have sequential `prior_segment_translations` dependency).
- Changing Pass 1 or Pass 3 logic.
- Async refactor of `LLMClient` — the existing synchronous client is reused.

## Owned Files Or Modules

- `docs/40-tasks/task-35-pass2-parallel-execution.md`
- `docs/20-lld/lld-35-pass2-parallel-execution.md`
- `src/resemantica/settings.py`
- `src/resemantica/translation/pipeline.py`
- `resemantica.toml`
- `resemantica-pilot.toml`

## Interfaces To Satisfy

### Config

```toml
[translation]
pass2_concurrency = 3
```

Default in code: `TranslationConfig.pass2_concurrency: int = 2`.

### Thread safety

- `LLMClient.generate_text()` is called concurrently from multiple threads. The underlying OpenAI client's connection pool (`httpx`) is thread-safe.
- Usage tracking counters (`llm_request_count`, `llm_prompt_tokens`, etc.) may see minor inaccuracy under concurrent access — acceptable for diagnostic data.
- Per-block results (`block_result`, `structure_checks`, `fidelity_check`) are returned from each thread and merged serially after all tasks complete — no shared mutable state.

### Error handling

- If any parallel task raises (structure validation failure, restoration failure), the exception propagates after all tasks complete. Remaining tasks are still processed (failure is rare; the waste is acceptable for code simplicity).
- Failed pass1 blocks are filtered before parallel submission (no LLM call needed).
- Resegmented blocks remain a single atomic task (internal segments still sequential).

## Tests Or Smoke Checks

- **Integration test:** `test_pass2_parallel_runs_to_completion` — `translate_chapter_pass2` with `pass2_concurrency=3` on a 2-block chapter. Verify all blocks are processed and order is preserved.
- **Integration test:** `test_pass2_parallel_resegmented_blocks` — chapter with one resegmented block (multiple segments) and one normal block. Verify both complete correctly.
- Existing pass2 tests (`test_pass2_no_fidelity_errors_returns_original_draft`, etc.) continue to pass unchanged.
- `uv run ruff check src tests`

## Done Criteria

- `pass2_concurrency` declared in config, read from TOML, validated > 0.
- `translate_chapter_pass2` processes blocks in parallel up to `pass2_concurrency`.
- Block order in the output artifact matches the original pass1 order.
- All existing tests pass.
