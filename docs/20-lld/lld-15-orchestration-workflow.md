# LLD 15: Orchestration Workflow

## Summary

Task 15 closes the gap between the target architecture and the current command-dispatch implementation. The orchestration layer must own production execution, translation dispatch, reconstruction dispatch, reset dispatch, run state, and event emission. CLI and TUI are presentation/controllers over this core, not alternate execution paths.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli run-production --release <id> --run <id> [--dry-run]`
- `uv run python -m resemantica.cli run production --release <id> --run <id> [--dry-run]`
- `uv run python -m resemantica.cli translate-chapter --release <id> --run <id> --chapter <n>`
- `uv run python -m resemantica.cli translate-range --release <id> --run <id> --start <n> --end <n>`
- `uv run python -m resemantica.cli rebuild-epub --release <id> --run-id <id>`

Python:

- `OrchestrationRunner(release_id, run_id, config=None)`
- `OrchestrationRunner.run_production(dry_run=False, chapter_start=None, chapter_end=None)`
- `OrchestrationRunner.run_stage(stage_name, **stage_options)`
- `OrchestrationRunner.plan_production(chapter_start=None, chapter_end=None)`
- module-level compatibility wrapper `run_stage(...)` may remain, but must delegate to `OrchestrationRunner`.

## Stage Model

The production plan is explicit and inspectable. It should include:

- `preprocess-glossary`
- `preprocess-summaries`
- `preprocess-idioms`
- `preprocess-graph`
- `packets-build`
- `translate-range`
- `epub-rebuild`

`translate-chapter` is a callable stage for a single chapter. `translate-range` iterates chapters and records per-chapter status. `translate-pass3` should not remain a separate production stage unless the runner treats it as an internal chapter step.

## Data Flow

1. CLI, TUI, or tests construct an `OrchestrationRunner`.
2. The caller requests `run_production()` or `run_stage()`.
3. The runner validates transition legality and required stage options.
4. The runner writes run state and emits `stage_started`.
5. The runner invokes the subsystem service.
6. The runner writes checkpoints and emits artifact/validation/chapter events.
7. The runner writes final run state and emits `stage_completed`, `stage_failed`, or `run_finalized`.

## Translation Stage Behavior

`translate-chapter` must:

- require `chapter_number`
- emit `chapter_started`
- invoke pass1, pass2, and pass3 only when enabled
- persist pass checkpoints
- emit validation failures and artifact events
- emit `chapter_completed` with pass statuses

`translate-range` must:

- require `chapter_start` and `chapter_end`
- iterate inclusively in numeric order
- continue or stop according to an explicit policy; the default should stop on hard structural failures
- return aggregate success/failure metadata

## Event Contract

Events must satisfy `DATA_CONTRACT.md` minimum fields:

- `event_id`
- `event_type`
- `event_time`
- `run_id`
- `release_id`
- `stage_name`
- `chapter_number`
- `block_id`
- `severity`
- `message`
- `payload`
- `schema_version`

Use contract event names where practical:

- `stage_started`
- `stage_completed`
- `chapter_started`
- `chapter_completed`
- `validation_failed`
- `artifact_written`
- `warning_emitted`
- `run_finalized`

Existing dotted names may be preserved only through a compatibility shim if tests or downstream tools still consume them.

## CLI Dispatch Rule

Top-level CLI commands may parse arguments and render output, but must not call translation pass functions, packet builders, cleanup functions, or EPUB rebuild functions directly when an orchestration stage exists. Dispatch should be:

```text
CLI args -> OrchestrationRunner -> subsystem service -> events/checkpoints/artifacts
```

## Validation Ownership

The runner validates:

- unknown stage names
- illegal transitions
- missing chapter/range/run options
- checkpoint compatibility for resume/rerun
- production dry-run graph correctness

Subsystems retain domain validation, such as placeholder validation and graph consistency.

## Tests

- `run-production --dry-run` returns the ordered graph and writes no stage artifacts.
- `translate-chapter` runner stage calls pass1/pass2/pass3 in the correct order.
- `translate-range` emits chapter events for each chapter.
- CLI commands delegate to `OrchestrationRunner`.
- Illegal transitions and missing stage options fail before subsystem invocation.
- Existing `run production` remains compatible or is explicitly migrated with tests updated.

## Implementation Status

Implemented drift closure:

- Production execution is owned by `OrchestrationRunner.run_production()`.
- `translate-chapter` and `translate-range` are functional runner stages.
- CLI translation and reconstruction commands delegate through `OrchestrationRunner`.
- Remaining operator-console polish is tracked separately in `docs/40-tasks/task-19-tui-completion-and-smoke-validation.md`.
