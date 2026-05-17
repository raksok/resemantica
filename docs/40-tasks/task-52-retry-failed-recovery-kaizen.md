# Task 52: Failed Validation Retry Recovery Kaizen

## Milestone

M52

## Depends On

M51

## Goal

Recover cleanly from failed validation by retrying compact summary generation automatically and by giving operators a durable `run retry-failed` command for exhausted failures.

## Scope

- Automatic Chinese structured-summary retry: one initial attempt plus three retries.
- Failed summary generation is a hard `preprocess-summaries` failure, not a skipped chapter.
- Summary checkpoints do not advance past a failed story chapter.
- `run retry-failed` plans and executes recovery for summaries, glossary, idioms, graph, packets, and translation.
- EPUB extract/rebuild remain out of scope for v1 retry-failed recovery.

## Owned Files Or Modules

- `src/resemantica/summaries/generator.py`
- `src/resemantica/summaries/pipeline.py`
- `src/resemantica/orchestration/retry_failed.py`
- `src/resemantica/cli.py`
- summary and orchestration tests
- relevant LLD and repo-map docs

## Interfaces To Satisfy

- `uv run python -m resemantica.cli run retry-failed -r <release> -R <run> --stage <stage|all>`
- `--chapter`, `--start`, `--end`, and `--dry-run`
- Retry stages: `preprocess-summaries`, `preprocess-glossary`, `preprocess-idioms`, `preprocess-graph`, `packets-build`, `translate-range`, `all`

## Tests Or Smoke Checks

- Summary retry succeeds after invalid JSON using reason-only feedback.
- Exhausted summary failure persists one failed draft and stops story assembly.
- `retry-failed --dry-run` reports retryable summary failures.
- Glossary and idiom conflicts are reported as review-required, not retried.
- Targeted summary/orchestration/CLI tests, ruff, mypy, and full pytest pass.

## Done Criteria

- Failed summary validation cannot silently create continuity holes.
- Operator dry-run shows retryable and non-retryable recovery units.
- Applying retry-failed delegates to existing stage runners without force by default.
- Docs describe the retry behavior and recovery command.
