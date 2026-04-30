# LLD 18: TUI And Events

## Summary

Task 18 turns the Textual app from a polling dashboard into an operator console over orchestration. The TUI must launch workflows, subscribe to live events, show paragraph-level translation progress, and provide reset/cleanup preview and execution controls.

## Public Interfaces

Python:

- `EventBus.subscribe(event_type, callback)`
- `EventBus.unsubscribe(event_type, callback)`
- `EventBus.publish(event)`
- `TUIAdapter.launch_workflow(workflow_name, **options)`
- `TUIAdapter.preview_reset(scope, run_id=None)`
- `TUIAdapter.apply_reset(scope, run_id=None)`
- `ResetPreviewScreen`

Compatibility:

- module-level `subscribe()`, `unsubscribe()`, and `emit_event()` may remain, but should delegate to the shared `EventBus`.

## Event Bus Behavior

The event bus must:

- persist events through the existing tracking repository
- notify live subscribers after successful persistence
- support wildcard or all-events subscriptions if useful for event log widgets
- avoid duplicate callback registration for the same subscriber
- tolerate subscriber exceptions without breaking event persistence

The bus must preserve the `DATA_CONTRACT.md` event fields.

## Granular Translation Events

Translation must emit events with `chapter_number` and `block_id` where relevant:

- `paragraph_started`
- `paragraph_completed`
- `paragraph_retry`
- `paragraph_skipped`
- `risk_detected`
- `validation_failed`
- `artifact_written`

Events may be emitted directly from translation code or from orchestration wrappers. Prefer orchestration-owned emission when it avoids coupling pass logic to UI behavior.

## TUI Adapter

`TUIAdapter` is the only TUI-facing execution controller.

Responsibilities:

- construct or receive an `OrchestrationRunner`
- launch preprocessing, translation, reconstruction, production, and reset workflows
- convert UI options into runner stage options
- expose current run/release context
- return immediate launch/preview results suitable for screen rendering

The adapter must not duplicate pipeline logic.

## Screens

Required functional screens:

- Dashboard: current run state, active stage, recent events, final status.
- Preprocessing: stage list plus action controls to run preprocessing/production.
- Translation: chapter/block progress, current pass, paragraph event stream.
- Event Log: real-time events with severity, event type, chapter, block, and message.
- ResetPreviewScreen: cleanup scope selector, delete/preserve preview, apply control disabled until preview exists.
- Artifacts: run/release artifact browsing.
- Settings: read-only effective configuration unless a later task adds editing.

The existing `CleanupScreen` may be replaced by or refactored into `ResetPreviewScreen`.

## Data Flow

```text
TUI screen action -> TUIAdapter -> OrchestrationRunner -> subsystem
                                  -> EventBus -> live TUI widgets
                                  -> tracking DB -> reload/history views
```

Screen refresh may still poll run state for resilience, but live event widgets should subscribe to the event bus.

## Failure And Safety

- workflow launch buttons must validate `release_id` and `run_id`
- destructive cleanup apply must be disabled until a matching preview plan exists
- cleanup apply must show the persisted plan scope and target count
- subscriber failures should emit or log warnings without crashing the app

## Tests

- `TUIAdapter.launch_workflow()` delegates to `OrchestrationRunner`
- event log receives events through `EventBus.subscribe()`
- duplicate subscriptions do not duplicate displayed events
- paragraph/risk/retry translation events include chapter and block IDs
- reset preview renders delete and preserve targets
- reset apply is disabled until preview exists

## Migration Notes

Current drift to fix:

- TUI screens are mostly read-only.
- screens poll SQLite rather than subscribing to live events.
- no `TUIAdapter` exists.
- no `EventBus` class exists.
- no `ResetPreviewScreen` exists.
- chapter spine and block progress are placeholders rather than run-derived state.
