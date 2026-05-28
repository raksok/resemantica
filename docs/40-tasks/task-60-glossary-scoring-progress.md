# Task 60: Glossary Scoring Progress

## Milestone

M60

## Depends On

M59

## Goal

Make long glossary corpus scoring phases visible in CLI, TUI, logs, and event history without changing candidate scoring or filtering behavior.

## Scope

- Add optional scoring progress callbacks to C-value and composite scoring.
- Emit scoring started, progress, and completed events from glossary discovery.
- Render generic `.progress` events in CLI and TUI progress models.
- Sample `.progress` events under reduced event persistence.
- Document the new events and troubleshooting guidance.

## Interfaces

- CLI flags: unchanged.
- Scoring output: unchanged.
- Event payloads: new `preprocess-glossary.discover.scoring.*` events.

## Tests

- Scoring results are identical with and without a progress callback.
- C-value and composite phases report start, progress, and completion callbacks.
- Small candidate sets emit final progress updates.
- Glossary discovery emits scoring events before deterministic filter completion.
- CLI and TUI progress models consume `.progress` payloads.
- Reduced event persistence samples `.progress` events.

## Done Criteria

- Large glossary scoring runs show bounded progress updates.
- Tracking DB persistence remains bounded in reduced mode.
- Focused glossary, observability, TUI, CLI, ruff, and mypy checks pass.
