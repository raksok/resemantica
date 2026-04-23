# LLD 07: Orchestration And Events

## Summary

Centralize execution control, stage ordering, retries, resume behavior, cleanup planning, and event emission so every operator surface reflects the same truth.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli run production`
- `uv run python -m resemantica.cli run resume`
- `uv run python -m resemantica.cli run cleanup-plan`
- `uv run python -m resemantica.cli run cleanup-apply`

Python modules:

- `orchestration.runner.run_stage()`
- `orchestration.resume.resume_run()`
- `orchestration.cleanup.plan_cleanup()`
- `orchestration.cleanup.apply_cleanup()`
- `orchestration.events.emit_event()`

Event model minimum fields:

- `event_id`
- `event_type`
- `event_time`
- `run_id`
- `release_id` nullable
- `stage_name`
- `chapter_number` nullable
- `block_id` nullable
- `severity`
- `message`
- `payload`
- `schema_version`

## Data Flow

1. CLI, TUI, or a production workflow requests a stage action.
2. Orchestration validates legal state transition and checkpoint compatibility.
3. The runner invokes the relevant subsystem service.
4. All major stage transitions emit structured events.
5. Retries emit explicit retry events with reason and attempt count.
6. Cleanup runs as a two-step workflow: plan first, apply second.
7. CLI, TUI, and tracking consume the same event stream and run metadata.

## Validation Ownership

- orchestration validates legal stage transitions
- cleanup apply refuses to run without a matching cleanup plan
- resume validates checkpoint compatibility before continuing

## Resume And Rerun

- rerun behavior is stage-scoped and hash-aware
- resume is driven by persisted checkpoints, not inferred from filesystem guesses
- cleanup never deletes authority state outside its declared scope

## Tests

- legal and illegal stage transitions
- retry event emission
- cleanup plan/apply contract
- resume from persisted checkpoint state

## Out Of Scope

- TUI widget design
- MLflow-specific rendering logic
