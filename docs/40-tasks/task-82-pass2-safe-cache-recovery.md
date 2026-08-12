# Task 82: Pass2 Safe Cache Recovery

## Milestone

M82

## Depends On

M81

## Goal

Retry failed Pass 2 chapters without reusing invalid cached outputs or rerunning valid sibling blocks.

## Scope

- Revalidate cached Pass 2 blocks with the current structural, restoration, and fidelity validators.
- Reuse only passing cached blocks and rebuild their validation records.
- Feed exact deterministic validation errors into the affected block's single-block repair attempts.
- Preserve exhausted invalid outputs for diagnosis without emitting completion events.
- Keep Pass 3 blocked until every Pass 2 block passes.

## Interfaces To Satisfy

- CLI arguments, translation settings, prompt versions, and database schemas remain unchanged.
- `run retry-failed --stage translate-range` continues with `force=false` and repairs only invalid or missing mappings.
- Extra, duplicate, or identity-mismatched cached mappings remain hard artifact errors.

## Documentation

- LLD: `../20-lld/lld-82-pass2-safe-cache-recovery.md`
- Update the single-chapter, Pass 2 retry, batching, architecture, and troubleshooting docs.

## Tests Or Smoke Checks

- `uv run --extra dev pytest tests\translation tests\orchestration -q`
- `uv run --extra dev ruff check src\resemantica tests`
- `uv run --extra dev mypy src\resemantica`

## Done Criteria

- A chapter-760-shaped cached `掬` failure is regenerated while valid siblings are reused.
- Retry prompts include the exact previous validation errors.
- Failed fidelity outputs remain diagnostic artifacts and never emit `paragraph_completed`.
- Chapter reports and checkpoints remain failed until all Pass 2 checks pass.
