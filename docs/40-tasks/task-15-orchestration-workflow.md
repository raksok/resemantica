# Task 15: Orchestration & Workflow

## Milestone And Depends On

Milestone: M15

Depends on: M10-M14B

## Goal

Close the orchestration drift by making the orchestration layer the shared execution core for production, translation, reconstruction, resume, and reset workflows.

## Scope

In:

- Add an `OrchestrationRunner` service in `src/resemantica/orchestration/runner.py`.
- Implement `OrchestrationRunner.run_production()` as the baked-in full workflow.
- Implement `OrchestrationRunner.run_stage()` for all registered stages, including `translate-chapter`, `translate-range`, `epub-rebuild`, and `reset`.
- Replace CLI-direct execution for `translate-chapter`, `translate-range`, and `rebuild-epub` with orchestration calls.
- Add a `run-production` CLI entrypoint with `--dry-run`, while preserving existing `run production` compatibility if desired.
- Ensure stage, chapter, retry, validation, artifact, and finalization events are emitted by orchestration.
- Persist run state and checkpoints through the shared tracking/storage layer.

Out:

- Changing translation pass prompt behavior.
- Rewriting EPUB reconstruction internals beyond invoking the formal stage.
- Updating the TUI dashboard (covered by Task 18).

## Owned Files Or Modules

- `src/resemantica/orchestration/runner.py`
- `src/resemantica/orchestration/models.py`
- `src/resemantica/cli.py`
- `src/resemantica/orchestration/events.py`
- `src/resemantica/orchestration/resume.py`
- `tests/orchestration/`
- `tests/cli/`

## Interfaces To Satisfy

- `OrchestrationRunner`
- `OrchestrationRunner.run_production()`
- `OrchestrationRunner.run_stage(stage_name, ...)`
- `OrchestrationRunner.run_stage("translate-chapter", chapter_number=...)`
- `OrchestrationRunner.run_stage("translate-range", chapter_start=..., chapter_end=...)`
- `OrchestrationRunner.run_stage("reset", scope=..., dry_run=...)`
- `resemantica run-production --release <id> --run <id> --dry-run`
- `resemantica run production --release <id> --run <id>`
- CLI commands for `translate-chapter`, `translate-range`, and `rebuild-epub`.

## Tests Or Smoke Checks

- Unit test production dry-run returns the expected execution graph without invoking stages.
- Unit test `translate-chapter` invokes pass1, pass2, and optional pass3 for one chapter through the runner.
- Unit test `translate-range --start 1 --end 5` invokes the runner and emits chapter events.
- Unit test `rebuild-epub` invokes the `epub-rebuild` stage through the runner.
- Run `uv run --with pytest pytest tests/orchestration tests/cli -q`.
- Smoke check `uv run python -m resemantica.cli run-production --release <id> --run <id> --dry-run`.
- Verify that chapter completion checkpoints are correctly saved during `translate-range`.

## Done Criteria

- Production workflow is owned by `OrchestrationRunner`, not by a CLI loop.
- CLI translation and reconstruction commands no longer call lower-level pipelines directly.
- `translate-chapter` and `translate-range` are functional orchestration stages, not stubs.
- A dry-run production graph is inspectable and deterministic.
- Events use the shared event contract for all major workflow transitions.
- `docs/20-lld/lld-15-orchestration-workflow.md` is implemented and kept in sync.
