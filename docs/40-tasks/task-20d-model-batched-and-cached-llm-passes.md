# Task 20d: Model-Batched + Cached LLM Passes

## Milestone And Depends On

Milestone: M20D

Depends on: M20A, M20B, M20C

## Goal

Reduce model swapping overhead by running compatible LLM work in model-grouped batches and caching deterministic extraction outputs where artifact inputs and prompt versions have not changed.

## Scope

In:
- Add a model-batched translation range path: pass1 for all chapters, then pass2 for all chapters, then pass3 for all chapters.
- Preserve existing per-chapter translation command behavior.
- Add cache checks for glossary discovery, idiom detection, graph extraction, and summary generation based on source hash, prompt version, model name, and chunk metadata.
- Use existing artifacts/checkpoints where valid instead of re-calling the model.
- Keep rerun/resume behavior deterministic.

Out:
- Parallel execution.
- Changing translation pass prompt templates.
- Changing promotion/validation semantics.
- Removing the existing per-chapter orchestration path.

## Owned Files Or Modules

- `src/resemantica/orchestration/runner.py`
- `src/resemantica/translation/pipeline.py`
- Preprocessing extractors and pipelines
- Existing checkpoint/cache repositories or a new small cache helper
- `docs/20-lld/lld-20d-model-batched-and-cached-llm-passes.md`

## Interfaces To Satisfy

- Add an opt-in orchestration option for batched translation range, defaulting to current behavior unless the LLD selects it as the production default.
- Existing `translate-chapter` behavior remains chapter-local.
- Cache identity includes release ID, chapter number, source hash, model name, prompt version, stage name, and chunk index when applicable.
- Cached outputs must be validated before reuse.

## Tests Or Smoke Checks

- Unit test batched translation order is all pass1, then all pass2, then all pass3 for a range.
- Unit test failure in a later pass records completed earlier-pass artifacts without corrupting checkpoints.
- Unit test cache hit skips LLM call and cache miss calls the model.
- Regression tests for `translate-chapter` and `translate-range`.
- Run `uv run pytest tests/orchestration tests/translation tests/glossary tests/summaries tests/idioms tests/graph`.
- Run `uv run ruff check src tests`.

## Done Criteria

- Large translation ranges can run in model-grouped pass order.
- Valid cached extraction outputs are reused across reruns.
- Existing per-chapter command behavior remains supported.
- Tests prove ordering, cache identity, and failure handling.
