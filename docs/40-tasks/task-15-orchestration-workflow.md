# Task 15: Orchestration & Workflow

## Goal

Ensure the centralized orchestration layer manages all production and maintenance workflows, eliminating CLI-direct bypasses and ensuring full-novel translation support.

## Scope

In:

- Implementing the complete `run-production` workflow in `src/resemantica/orchestration/runner.py`.
- Fixing the `translate-chapter` stage to correctly iterate over chapters (it is currently a stub).
- Refactoring `src/resemantica/cli.py` commands (`translate-chapter`, `translate-range`, `epub-rebuild`) to invoke the `OrchestrationRunner` instead of executing logic directly.
- Ensuring event emission is consistent across the orchestration layer.

Out:

- Modifying actual translation pass logic (this is strictly about orchestration and dispatch).
- Updating the TUI dashboard (covered by Task 18).

## Owned Files Or Modules

- `src/resemantica/orchestration/runner.py`
- `src/resemantica/cli.py`
- `src/resemantica/orchestration/events.py`

## Interfaces To Satisfy

- `OrchestrationRunner.run_production()`
- `OrchestrationRunner.run_stage("translate-chapter", ...)`
- CLI commands for `translate-chapter`, `translate-range`, and `rebuild-epub`.

## Tests Or Smoke Checks

- Run `resemantica run-production --dry-run` to verify the execution graph.
- Run `resemantica translate-range --start 1 --end 5` and verify orchestration events are emitted.
- Verify that chapter completion checkpoints are correctly saved during `translate-range`.

## Done Criteria

- The `run-production` workflow successfully iterates through preprocessing, translation, and reconstruction.
- CLI commands for translation and reconstruction use the orchestration runner.
- The `translate-chapter` stage correctly handles the chapter sequence.
- Orchestration events are emitted for all major workflow transitions.
