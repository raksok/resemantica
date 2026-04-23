# Task 11: Cleanup Workflow

- **Milestone:** M11
- **Depends on:** M10

## Goal

Implement explicit, scoped cleanup with preview-first behavior and preservation of protected inputs, config, prompts, and authority state.

## Scope

In:

- cleanup planning models and reports
- scoped filesystem and SQLite cleanup
- dry-run preview
- cleanup events and bookkeeping

Out:

- automated archival policies
- TUI polish beyond orchestration-facing hooks
- cleanup of protected assets by default

## Owned Files Or Modules

- `src/resemantica/orchestration/cleanup.py`
- `src/resemantica/db/`
- `tests/orchestration/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-11-cleanup-details.md`
- CLI: `uv run python -m resemantica.cli run cleanup-plan`
- CLI: `uv run python -m resemantica.cli run cleanup-apply`
- Python: `orchestration.cleanup.plan_cleanup()`
- Python: `orchestration.cleanup.apply_cleanup()`

## Tests Or Smoke Checks

- dry-run preview accuracy
- scope isolation across run, translation, preprocess, cache, and all
- preservation of source EPUBs, config, prompts, and manual overrides by default
- release-aware filesystem and SQLite cleanup

## Done Criteria

- cleanup apply refuses to run without a persisted matching plan
- dry-run shows exactly what would be deleted and preserved
- run-level cleanup does not affect locked glossary or validated summaries
- cleanup reports and events are emitted for preview and apply workflows
