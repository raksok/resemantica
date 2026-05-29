# Task 60: Glossary Scoring And Finalization Progress

## Milestone

M60

## Depends On

M59

## Goal

Make long glossary corpus scoring and finalization phases visible in CLI, TUI, logs, and event history without changing candidate scoring, filtering, deduplication, or artifact behavior.

## Scope

- Add optional scoring progress callbacks to C-value and composite scoring.
- Emit prefilter, scoring, deterministic filter, LLM eval, dedup, persistence, checkpoint, candidate snapshot, and failure events from glossary discovery.
- Render generic `.progress` events in CLI and TUI progress models.
- Sample `.progress` events under reduced event persistence.
- Document the new events and troubleshooting guidance.

## Interfaces

- CLI flags: unchanged.
- Scoring output: unchanged.
- Event payloads: new `preprocess-glossary.discover.prefilter.*`, `.scoring.*`, `.filter.*`, `.eval.*`, `.dedup.*`, `.checkpoint.completed`, `.snapshot.artifact_written`, and `.failed` events under `preprocess-glossary.discover.*`.

## Tests

- Scoring results are identical with and without a progress callback.
- C-value and composite phases report start, progress, and completion callbacks.
- Small candidate sets emit final progress updates.
- Glossary discovery emits prefilter and scoring events before deterministic filter completion.
- Glossary discovery emits filter, eval, dedup, persistence, checkpoint, and snapshot events before discover completion.
- Glossary discovery emits warning events for nonfatal eval batch failures and error events for fatal discover phase failures.
- Zero-candidate discovery still emits finalization skip/checkpoint/snapshot events.
- CLI and TUI progress models consume `.progress` payloads.
- Reduced event persistence samples `.progress` events.

## Done Criteria

- Large glossary scoring runs show bounded progress updates.
- Operators can see whether filtering, eval, alias clustering, checkpointing, and candidate snapshot writing completed.
- Tracking DB persistence remains bounded in reduced mode.
- Focused glossary, observability, TUI, CLI, ruff, and mypy checks pass.
