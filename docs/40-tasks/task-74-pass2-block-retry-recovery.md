# Task 74: Pass2 Block Retry Recovery

## Goal

Recover from transient pass2 validation failures before failing `translate-range`, using block-level retries.

## Implementation

- Add `[translation].pass2_validation_retries`, default `2`, validated as `>= 0`.
- Wrap pass2 block processing with a retry loop for structural, restoration, and fidelity validation failures.
- Emit `pass2.retry` events for retry attempts.
- Keep prompt-budget and non-validation failures outside this retry loop.
- Fix `run retry-failed --stage translate-range` to recognize `translation_checkpoints.status = 'success'`.

## Documentation

- LLD: `../20-lld/lld-74-pass2-block-retry-recovery.md`
- Update LLD 02 and LLD 35 for pass2 retry behavior.
- Update configuration and command docs.

## Validation

- `uv run --extra dev pytest tests\translation -q`
- `uv run --extra dev pytest tests\orchestration\test_batched_translation.py -q`
- `uv run --extra dev pytest tests\orchestration\test_orchestration.py -q -k "retry_failed or RetryFailed"`
- `uv run --extra dev ruff check src\resemantica\translation src\resemantica\orchestration tests\translation tests\orchestration`
