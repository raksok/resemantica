# Task 57: Summary Validation Gates

## Milestone

M57

## Depends On

M56

## Goal

Treat non-empty LLM summary-validation `flags` as retryable summary-generation failures so suspect continuity cannot feed story memory, packets, graph continuity, or translation pass 1.

## Scope

- Run `summary_zh_validate.txt` inside the structured-summary attempt loop.
- Fail any attempt with one or more validation flags, including unknown future flags and `<parse_error>`.
- Retry immediately with compact correction feedback that names the content-validation flags.
- On exhausted retries, persist a failed summary draft and failed structured/short audit rows, but do not create story-so-far rows.
- Keep validator `warnings` non-fatal and artifact-only.
- Make downstream summary reads approved-only by default.
- Emit one aggregated `preprocess-summaries.llm_validation_warning` per flagged attempt.

## Owned Files Or Modules

- `src/resemantica/summaries/generator.py`
- `src/resemantica/summaries/pipeline.py`
- `src/resemantica/db/summary_repo.py`
- `src/resemantica/orchestration/gates.py`
- `src/resemantica/orchestration/retry_failed.py`
- summary, packet, and orchestration tests

## Interfaces To Satisfy

- `GeneratedChapterSummary.llm_validation_flags` is empty for successful summaries.
- `GeneratedChapterSummary.llm_validation_warnings` carries non-fatal validator warnings.
- `summary_repo.get_validated_summary()` and `list_validated_summaries()` default to `validation_status='approved'`.
- Audit callers pass `validation_status=None` to inspect failed rows.
- `retry-failed` plans `preprocess-summaries` for `llm_content_validation_failed`.

## Tests Or Smoke Checks

- Flagged attempt followed by clean retry succeeds and persists approved rows only.
- Repeated flags exhaust retries, fail the chapter, write failed audit rows, and do not advance checkpoints.
- Failed rows are invisible to packet and gate default reads.
- Validator warnings remain non-fatal and do not emit warning events.
- Aggregated warning events include `flags`, `flag_count`, `attempt_number`, and `action`.

## Done Criteria

- No failed summary row can be consumed by packets, graph continuity, stage gates, or translation.
- Failed content-validation chapters are recoverable through `run retry-failed`.
- Documentation distinguishes fatal validator `flags` from non-fatal validator `warnings`.
