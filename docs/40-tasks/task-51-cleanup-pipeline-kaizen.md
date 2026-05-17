# Task 51: Cleanup Pipeline Kaizen

- **Milestone:** M51
- **Depends on:** M11, M49

## Goal

Harden cleanup so every operator surface uses the same scopes, every apply is backed by a matching persisted plan, and stage-oriented cleanup can reset downstream work while preserving extracted artifacts.

## Scope

In:

- shared cleanup scope contract
- `keep-extracted` cleanup scope
- scope-specific SQLite cleanup targets
- cleanup plan identity and path-root validation
- CLI/TUI cleanup scope parity
- cleanup docs and focused regression tests

Out:

- storage schema redesign
- archival/backup policy
- cleanup of authority state beyond explicitly run-owned rows

## Owned Files Or Modules

- `src/resemantica/orchestration/cleanup.py`
- `src/resemantica/cli.py`
- `src/resemantica/tui/screens/cleanup_wizard.py`
- `tests/orchestration/`
- `tests/cli/`
- `tests/tui/`

## Interfaces To Satisfy

- CLI: `uv run python -m resemantica.cli run cleanup-plan --scope <scope>`
- CLI: `uv run python -m resemantica.cli run cleanup-apply --scope <scope>`
- Python: `orchestration.cleanup.plan_cleanup()`
- Python: `orchestration.cleanup.apply_cleanup()`
- TUI: Cleanup Wizard scope cycle and preview/apply flow

## Tests Or Smoke Checks

- `keep-extracted` preserves `extracted/` and extraction metadata while deleting downstream artifacts.
- `cache` deletes no SQLite rows.
- apply refuses missing, mismatched, or out-of-root plans.
- CLI parses `keep-extracted` and `factory`.
- TUI scope cycle includes `keep-extracted` and categorizes Windows paths.

## Done Criteria

- all cleanup scopes are defined once and reused by backend, CLI, and TUI
- cleanup apply validates plan schema, release/run identity, scope, expected root, and target containment
- `--force` bypasses only scope mismatch, not release/run or path safety
- cleanup docs describe filesystem and SQLite behavior for each scope
