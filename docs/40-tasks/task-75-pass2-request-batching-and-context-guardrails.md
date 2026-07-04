# Task 75: Pass2 Request Batching And Context Guardrails

## Milestone

M75

## Depends On

M74

## Goal

Reduce Pass 2 request count by batching normal block audits while preserving the existing single-block retry and validation recovery behavior.

## Scope

- Add `[translation].pass2_batch_max_blocks` with default `8`.
- Add `translate_pass2_batch.txt`.
- Pack normal Pass 2 blocks into token-bounded batches.
- Keep resegmented blocks on the existing sequential segment path.
- Fall back only affected blocks through `_process_pass2_block()`.
- Record batching metadata and batch lifecycle events.

## Owned Files Or Modules

- `src/resemantica/settings.py`
- `src/resemantica/translation/pass2.py`
- `src/resemantica/translation/pipeline.py`
- `src/resemantica/llm/prompts/translate_pass2_batch.txt`
- translation/settings tests
- LLD and manual docs

## Interfaces To Satisfy

- Existing Pass 2 artifact `blocks` shape remains compatible.
- `pass2_batch_max_blocks = 1` uses existing one-block scheduling.
- Batch prompt budget checks include matching throttle-group system prompt overhead.
- Batch parser requires exact one-result-per-input-block mapping.

## Tests Or Smoke Checks

- `uv run --extra dev pytest tests\translation -q`
- `uv run --extra dev pytest tests\orchestration\test_batched_translation.py -q`
- `uv run --extra dev pytest tests\orchestration\test_orchestration.py -q -k "retry_failed or RetryFailed"`
- `uv run --extra dev ruff check src\resemantica\translation src\resemantica\llm src\resemantica\settings.py tests\translation tests\orchestration tests\test_settings_models.py`

## Done Criteria

- Normal Pass 2 blocks batch by default.
- Oversized, malformed, or invalid batch results recover through existing single-block logic.
- Existing resegmented-block behavior is unchanged.
- Requested tests and lint pass.
