# LLD 10: Orchestration And Events

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

## Operator Logging Contract

Operational signals with run context must be emitted through `emit_event()` or a pipeline-local `_emit()` wrapper. This persists the event in the tracking DB and writes the paired structured Loguru JSONL record. Direct Loguru warning/error messages are reserved for helper diagnostics that do not know `run_id`/`release_id`, or for diagnostics paired by a callback into the run-context caller.

The event-backed path is required for operator-affecting lifecycle, warning, skip, retry, fallback, validation, artifact, and failure decisions. Current required failure/repair signals include:

- `preprocess-summaries.story_compact_repaired`: compact continuity exceeded budget and was repaired; payload includes `attempt`, `token_count`, `max_tokens`, and `cache_repaired`.
- `preprocess-summaries.story_compact_repair_failed`: compact continuity repair exhausted or returned empty output; payload includes `reason`, `attempt`, `token_count`, and `max_tokens`.
- `preprocess-continuity.chapter_failed`: graph continuity refresh failed for a chapter; payload includes `reason`.
- `preprocess-graph.validation_failed`: graph validation failed before snapshot promotion; payload includes `errors`.
- `translate-chapter.pass1.failed`, `translate-chapter.pass2.failed`, `translate-chapter.pass3.failed`: batched range pass-level exception handlers failed; payload includes `pass_name` and `reason`.
- `translate-chapter.bundle_context_missing`: translation continued without packet bundle context; payload includes `pass_name`, `reason`, and `bundle_path` when available.

## Data Flow

1. CLI, TUI, or a production workflow requests a stage action.
2. Orchestration validates legal state transition and checkpoint compatibility.
3. The runner invokes the relevant subsystem service.
4. All major stage transitions emit structured events.
5. Retries emit explicit retry events with reason and attempt count.
6. Cleanup runs as a two-step workflow: plan first, apply second.
7. CLI, TUI, and tracking consume the same event stream and run metadata.

## Summary Validation Events

`preprocess-summaries.llm_validation_warning` is emitted at most once per flagged LLM validation attempt and chapter. Its payload includes:

- `flags`: all fatal validator flags from that attempt
- `flag_count`
- `attempt_number`
- `action`: `retry` while retry budget remains, or `fail` on the exhausted attempt

Validator `warnings` from `summary_zh_validate.txt` do not emit warning events. They are written to summary artifacts as review notes.

When content-validation retries exhaust, `preprocess-summaries.chapter_failed` is emitted with severity `error`, `reason = "llm_content_validation_failed"`, and the final `llm_validation_flags` payload.

## Chunk Events

Long batch-order stages emit chunk lifecycle events:

- `preprocess-summaries.chunk_started`
- `preprocess-summaries.chunk_completed`
- `preprocess-summaries.chunk_failed`
- `translate-range.chunk_started`
- `translate-range.chunk_completed`
- `translate-range.chunk_failed`

Payloads include `chunk_index`, `chunk_count`, `chapter_start`, `chapter_end`, `chunk_size`, and `last_good_chapter`. For `preprocess-summaries`, `last_good_chapter` is the current English phase checkpoint; a completed summary chunk is resume-skippable only when the stored chunk range matches the current chunk and that value is at least the chunk's `chapter_end`. Failure events also include the failure reason or failed chapter data when available.

## Validation Ownership

- orchestration validates legal stage transitions
- cleanup apply refuses to run without a matching cleanup plan
- resume validates checkpoint compatibility before continuing

## Resume And Rerun

- rerun behavior is stage-scoped and hash-aware
- default reruns for the same `release_id` and `run_id` resume by skipping completed durable work
- `--force` bypasses internal checkpoints and cache hits for the requested command scope
- `--allow-rewind` only permits a stage-order transition; it does not disable internal resume
- resume is driven by persisted SQLite checkpoints or authoritative metadata, not inferred from filesystem guesses
- stage checkpoints advance only after the corresponding durable unit has been safely written
- chunk checkpoints advance only after the corresponding chunk has completed every phase/pass in that stage
- summary phase checkpoints remain authoritative per phase; summary chunk completion metadata cannot override a lagging `zh_last_chapter`, `story_last_chapter`, or `en_last_chapter`
- cleanup never deletes authority state outside its declared scope

## Tests

- legal and illegal stage transitions
- retry event emission
- cleanup plan/apply contract
- resume from persisted checkpoint state

## Out Of Scope

- TUI widget design
- backend-specific dashboard rendering logic
