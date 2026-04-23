# LLD 11: Detailed Cleanup Workflow

## Summary

Implement the explicit, scoped, and previewable cleanup/reset workflow to allow safe project restarts and artifact management.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli run cleanup-plan --scope <run|translation|preprocess|cache|all> [--run-id <id>]`
- `uv run python -m resemantica.cli run cleanup-apply --scope <run|translation|preprocess|cache|all> [--run-id <id>]`

Python modules:

- `orchestration.cleanup.plan_cleanup()`
- `orchestration.cleanup.apply_cleanup()`

Artifacts:

- cleanup plan (JSON)
- cleanup report (JSON)

## Data Flow

1. Resolve requested scope and run/release context.
2. Identify deletable artifacts:
    - `run`: specific run folder and SQLite run/checkpoint/cache rows.
    - `translation`: translation artifacts within a run.
    - `preprocess`: extracted text, glossary candidates, draft summaries, packets.
    - `cache`: LLM completion cache and intermediate artifacts.
    - `all`: everything except source EPUB and project config.
3. Generate a "Cleanup Plan" listing all targets for deletion and all preserved assets.
4. If `--dry-run` is not set, execute deletions and row removals.
5. Record the final Cleanup Report.

## Validation Ownership

- cleanup MUST NOT delete source EPUBs or configuration files by default
- cleanup MUST NOT delete authoritative `locked_glossary` unless scope is `all`
- plans must be generated and persisted before execution

## Resume And Rerun

- cleanup operations are themselves recorded in the event stream and SQLite bookkeeping

## Tests

- dry-run preview accuracy
- scope isolation (e.g., clearing one run doesn't affect another)
- preservation of inputs and config
- release-aware artifact deletion
