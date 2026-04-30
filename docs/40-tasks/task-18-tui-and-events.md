# Task 18: TUI & Operator Experience

## Milestone And Depends On

Milestone: M18

Depends on: M15, M17

## Goal

Transform the TUI from a read-only dashboard into an active operator console with granular visibility into translation progress and full control over workflows.

## Scope

In:

- Add an event bus abstraction suitable for live TUI subscriptions while preserving SQLite event persistence.
- Updating the translation pipeline (`src/resemantica/translation/`) or orchestration wrappers to emit granular events for paragraph starts, completions, retries, skips, risk detections, and validation failures.
- Add `TUIAdapter.launch_workflow()` as the TUI-facing controller over `OrchestrationRunner`.
- Adding action buttons or controls to TUI screens (e.g., `PreprocessingScreen`, `TranslationScreen`) to allow launching workflows directly from the TUI.
- Implementing real-time event log viewing in the TUI.
- Adding the "Reset/Cleanup" preview and execution screen to the TUI.
- Replace hard-coded chapter spine placeholders with run/release-derived progress where available.

Out:

- Redesigning the visual style beyond functional requirements.
- Changing orchestration state-machine rules except where needed to consume existing runner APIs.
- Styling the TUI beyond functional requirements.

## Owned Files Or Modules

- `src/resemantica/tui/app.py`
- `src/resemantica/tui/screens/`
- `src/resemantica/orchestration/events.py`
- `src/resemantica/translation/pipeline.py`
- `src/resemantica/tui/adapter.py` (new)
- `tests/tui/`
- `tests/translation/`

## Interfaces To Satisfy

- `TUIAdapter.launch_workflow()`
- `EventBus.subscribe()` for TUI widgets.
- `ResetPreviewScreen` in the TUI.
- real-time event log widget or panel.

## Tests Or Smoke Checks

- Unit test `TUIAdapter.launch_workflow()` delegates to `OrchestrationRunner`.
- Unit test TUI event log receives events through `EventBus.subscribe()`.
- Unit test translation emits paragraph/risk/retry events with chapter and block IDs.
- Unit test reset preview screen renders planned delete/preserve targets and refuses apply before preview.
- Launch a run from the TUI and verify that the dashboard updates in real-time as paragraphs are translated.
- Trigger a paragraph retry (mocked if necessary) and verify the event is visible in the TUI log.
- Preview a cleanup from the TUI and verify the target list is correct.
- Run `uv run --with pytest pytest tests/tui tests/translation -q`.

## Done Criteria

- The TUI can launch and manage preprocessing, translation, and reconstruction workflows.
- Granular translation events (paragraph level) are visible in the TUI.
- The TUI provides a functional interface for the Reset/Cleanup workflow.
- All orchestration events are correctly captured and displayed in the TUI's event log.
- `docs/20-lld/lld-18-tui-and-events.md` is implemented and kept in sync.

## Follow-Up

The remaining operator-console completion work is split into M19:

- `docs/40-tasks/task-21-tui-completion-and-smoke-validation.md`
- `docs/20-lld/lld-19-tui-completion-and-smoke-validation.md`
