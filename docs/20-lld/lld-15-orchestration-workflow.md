# LLD 15: Orchestration Workflow

## Summary

Task 15 closes the gap between the target architecture and the current command-dispatch implementation. The orchestration layer must own production execution, translation dispatch, reconstruction dispatch, reset dispatch, run state, and event emission. CLI and TUI are presentation/controllers over this core, not alternate execution paths.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli run-production --release <id> --run <id> [--dry-run]`
- `uv run python -m resemantica.cli run production --release <id> --run <id> [--dry-run]`
- `uv run python -m resemantica.cli run retry-failed --release <id> --run <id> --stage <stage|all> [--dry-run]`
- `uv run python -m resemantica.cli translate-chapter --release <id> --run <id> --chapter <n>`
- `uv run python -m resemantica.cli translate-range --release <id> --run <id> --start <n> --end <n>`
- `uv run python -m resemantica.cli rebuild-epub --release <id> --run-id <id>`

Python:

- `OrchestrationRunner(release_id, run_id, config=None)`
- `OrchestrationRunner.run_production(dry_run=False, chapter_start=None, chapter_end=None)`
- `OrchestrationRunner.run_stage(stage_name, **stage_options)`
- `OrchestrationRunner.plan_production(chapter_start=None, chapter_end=None)`
- `orchestration.retry_failed.plan_retry_failed(...)`
- `orchestration.retry_failed.execute_retry_failed(...)`
- module-level compatibility wrapper `run_stage(...)` may remain, but must delegate to `OrchestrationRunner`.

## Stage Model

The production plan is explicit and inspectable. It should include:

- `preprocess-summaries`
- `preprocess-glossary`
- `preprocess-idioms`
- `preprocess-graph`
- `preprocess-continuity`
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

## Production Resume Behavior

`run production` is resumable for the same release/run. Before execution, the runner reads `run_state`:

- no prior stage state: start at `preprocess-summaries`
- failed, stopped, or running stage: retry that same stage
- completed stage: start at the next stage
- completed `epub-rebuild`: return success without rerunning stages

If the saved checkpoint contains `chapter_start` or `chapter_end`, those bounds are reused when the operator does not pass explicit bounds on the new command. Explicit CLI bounds take precedence.

Internal stage resume is enabled by default. When production reaches summaries, glossary, idioms, graph, packets, or translation, the stage also skips its own completed durable units. Operators use `--force` on production or an individual command to rebuild the requested scope.

For chunked batch-order stages, `chunk_checkpoints` add a cleanup boundary without replacing normal stage checkpoints. `preprocess-summaries` still resumes from `summary_checkpoints` inside an incomplete chunk. Batched `translate-range` requires stored chunk bounds to cover the current chunk and audits the artifact block mappings behind `pass1_completed`, `pass2_completed`, and `pass3_completed`; a matching numeric chunk index or nominally completed checkpoint never makes a different range or incomplete artifact reusable. Incompatible retry ranges execute without overwriting the older row.

## Failed Unit Retry

`run retry-failed` is an operator recovery command, not a force rebuild. It inspects durable state and tracking events, reports retryable units and review-required blockers, and then delegates to existing stage runners with the smallest chapter scope it can infer.

Supported retry stages are:

- `preprocess-summaries`
- `preprocess-glossary`
- `preprocess-idioms`
- `preprocess-graph`
- `preprocess-continuity`
- `packets-build`
- `translate-range`
- `all`

`--dry-run` performs read-only discovery and prints the retry plan. `--chapter`, `--start`, and `--end` constrain discovery and execution. Summaries rewind `summary_checkpoints` to before the earliest affected chapter before execution; `llm_content_validation_failed` summary drafts are retryable and rerun summary generation with fresh correction feedback. Translation repair temporarily uses an explicit empty execution checkpoint, delegates block reuse to the translation artifacts, and restores the original production `RunState` afterward. Glossary and idiom conflicts are reported as review-required and are not retried automatically. EPUB rebuild/extract are intentionally excluded because they do not expose finer durable failed units.

Summary rows with `validation_status = "failed"` are audit evidence only. Production gates for packets and translation require approved summary rows, so flagged summaries fail and retry before packet assembly or translation pass 1 can consume them.

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
- fail the chapter and translation chunk when any extracted parent block lacks a successful Pass 1 result
- audit complete, non-empty final block coverage before reporting range success

When batched model order and chunking are active, `translate-range` runs pass1, pass2, and pass3 for one chunk before advancing to the next chunk. The stage checkpoint metadata includes chunk progress so production resume and cleanup can identify the last completed chunk. Reuse requires both range coverage and complete final artifacts. Pass 2 cannot run for a chapter with failed or missing Pass 1 blocks.

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

Top-level CLI commands may parse arguments and render output, but must not call translation pass functions, packet builders, cleanup functions, or EPUB rebuild functions directly when an orchestration stage exists. Direct CLI and TUI reconstruction dispatch always enables stage gates. Dispatch should be:

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

### Re-running Earlier Stages

Stages are normally forward-only. Attempting an earlier stage after a later one
has started raises an `Illegal stage transition` error.

When you need to re-run an earlier stage (e.g., to fix summary generation for
specific chapters), pass `--allow-rewind` / `-w`:

    rsem pre sum -r p1 -R 001 -w -s 1 -e 20

This clears the persisted run state and lets the stage execute. After
re-running, proceed forward with `rsem run resume` or individual
`rsem pre` / `rsem pac build` commands.

The `--allow-rewind` flag is available on `summaries`, `idioms`, `graph`,
`packets-build`, and `epub-rebuild`. It changes only stage-order validation.
It does not mean "ignore summary checkpoints", "rerun packet cache hits", or
"drop graph drafts".

For failed durable units, prefer:

    rsem run retry-failed -r p1 -R 001 --stage all --dry-run
    rsem run retry-failed -r p1 -R 001 --stage preprocess-summaries -s 10 -e 20

Use `--force` when the operator needs to rebuild:

    rsem pre sum -r p1 -R 001 --force -s 1 -e 20
    rsem pac build -r p1 -R 001 --force -C 12
    rsem run resume -r p1 -R 001 --force

`run production --force` starts again at `preprocess-summaries` and forwards
`force=True` to each stage. `run resume --force` keeps the resume start point
but tells each resumed stage to bypass its internal checkpoints.

After a crash in chunked summary or batched translation work, operators can preview and apply cleanup back to the last completed chunk:

    rsem run cleanup-plan -r p1 -R 001 --scope last-good-chunk --stage preprocess-summaries
    rsem run cleanup-apply -r p1 -R 001 --scope last-good-chunk --stage translate-range

## Tests

- `run-production --dry-run` returns the ordered graph and writes no stage artifacts.
- `translate-chapter` runner stage calls pass1/pass2/pass3 in the correct order.
- `translate-range` emits chapter events for each chapter.
- CLI commands delegate to `OrchestrationRunner`.
- `run retry-failed --dry-run` reports retryable and review-required units without mutation.
- `run retry-failed --stage preprocess-summaries` rewinds summary checkpoints and reruns the affected range.
- Illegal transitions and missing stage options fail before subsystem invocation.
- Existing `run production` remains compatible or is explicitly migrated with tests updated.

## Implementation Status

Implemented drift closure:

- Production execution is owned by `OrchestrationRunner.run_production()`.
- `translate-chapter` and `translate-range` are functional runner stages.
- CLI translation and reconstruction commands delegate through `OrchestrationRunner`.
- Remaining operator-console polish is tracked separately in `docs/40-tasks/task-21-tui-completion-and-smoke-validation.md`.
