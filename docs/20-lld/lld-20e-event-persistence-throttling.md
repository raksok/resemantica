# LLD 20e: Event Persistence Throttling For Huge Runs

## Summary

Keep live event delivery while reducing SQLite writes for repetitive progress events during huge runs.

## Problem Statement

Task 19 added broad pipeline event emissions. For 1000+ chapters and per-paragraph translation events, persisting every progress event can make `tracking.db` noisy and add overhead. Operators still need live progress, warnings, failures, and audit-significant lifecycle events.

## Technical Design

Add event persistence policy to settings:

```python
@dataclass(slots=True)
class EventsConfig:
    persistence_mode: str = "normal"  # normal | reduced
    progress_sample_every: int = 25
```

`normal` preserves current behavior for small runs. `reduced` persists all critical events and samples/coalesces repetitive progress events.

Critical events always persisted:

- `*.started`
- `*.completed`
- `*.failed`
- `*_failed`
- `validation_failed`
- `risk_detected`
- `*.chapter_skipped`
- `*.artifact_written`
- severity `warning` or `error`

Progress events that may be sampled in reduced mode:

- `*.paragraph_started`
- `*.paragraph_completed`
- high-volume chapter progress where no warning/error occurred

## EventBus Behavior

`EventBus.publish(event)` order:

1. Decide persistence through policy.
2. Persist if policy says yes.
3. Always notify exact and wildcard subscribers.
4. Catch subscriber exceptions as today.

This preserves CLI/TUI live progress even when not every progress event is written to SQLite.

## Tests

- In normal mode, current persistence behavior is unchanged.
- In reduced mode, subscribers receive every event.
- In reduced mode, warning/error/failure events are persisted.
- In reduced mode, sampled progress events write fewer rows for a simulated large run.
- CLI progress tests still pass.

## Out Of Scope

- JSON log throttling.
- Removing existing tracking tables.
- Changing event model fields.

## Implementation Notes

- Event persistence settings are available under `[events]` with defaults that preserve normal behavior.
- In reduced mode, EventBus samples repetitive chapter and paragraph progress persistence while still delivering every event to subscribers.
- Warning, error, failure, skipped, risk, validation, artifact, and lifecycle events remain persisted.
