# Task 20e: Event Persistence Throttling For Huge Runs

## Milestone And Depends On

Milestone: M20E

Depends on: M19, M20C

## Goal

Make EventBus persistence less chatty for 1000+ chapter runs while preserving live progress and important audit events.

## Scope

In:
- Add configurable event persistence policy for high-volume progress events.
- Keep subscriber delivery for live CLI/TUI progress.
- Persist lifecycle, warning, failure, risk, validation, artifact, and completion events by default.
- Coalesce or sample repetitive paragraph/chapter progress events for SQLite persistence.
- Add explicit tests for persisted versus delivered events.

Out:
- Removing EventBus wildcard subscription support.
- Changing tracking DB schema unless required by the LLD.
- Dropping warning/error events.
- Changing JSON log behavior.

## Owned Files Or Modules

- `src/resemantica/orchestration/events.py`
- `src/resemantica/tracking/repo.py`
- `src/resemantica/settings.py`
- `src/resemantica/cli_progress.py`
- `tests/tui/`, `tests/tracking/`, and event/progress tests
- `docs/20-lld/lld-20e-event-persistence-throttling.md`

## Interfaces To Satisfy

- Add config defaults for event persistence policy without requiring user config changes.
- `EventBus.publish(event)` still returns the event and notifies subscribers.
- Event persistence policy decides whether to call `save_event()`.
- Critical events are always persisted.

## Tests Or Smoke Checks

- Unit test chatty progress events are delivered to subscribers even when not all are persisted.
- Unit test warning/error/failure events are always persisted.
- Unit test default policy preserves current behavior for small runs.
- Unit test coalesced/sampled policy reduces SQLite writes for simulated large runs.
- Run `uv run pytest tests/tracking tests/tui tests/test_cli_progress.py`.
- Run `uv run ruff check src tests`.

## Done Criteria

- Huge runs can reduce tracking DB writes for repetitive progress events.
- CLI/TUI progress remains live and accurate enough for operators.
- Audit-significant events remain persisted.
- Tests cover delivery, persistence, and policy defaults.
