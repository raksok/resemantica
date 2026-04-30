# Task 18: TUI & Operator Experience

## Goal

Transform the TUI from a read-only dashboard into an active operator console with granular visibility into translation progress and full control over workflows.

## Scope

In:

- Updating the translation pipeline (`src/resemantica/translation/`) to emit granular events for paragraph starts, completions, retries, and risk detections.
- Adding "Action" buttons or controls to TUI screens (e.g., `PreprocessingScreen`, `TranslationScreen`) to allow launching workflows directly from the TUI.
- Implementing real-time event log viewing in the TUI.
- Adding the "Reset/Cleanup" preview and execution screen to the TUI.

Out:

- Modifying the orchestration runner's core state machine (this task is about event *emission* and UI *interaction*).
- Styling the TUI beyond functional requirements.

## Owned Files Or Modules

- `src/resemantica/tui/app.py`
- `src/resemantica/tui/screens/`
- `src/resemantica/orchestration/events.py`
- `src/resemantica/translation/pipeline.py`

## Interfaces To Satisfy

- `TUIAdapter.launch_workflow()`
- `EventBus.subscribe()` for TUI widgets.
- `ResetPreviewScreen` in the TUI.

## Tests Or Smoke Checks

- Launch a run from the TUI and verify that the dashboard updates in real-time as paragraphs are translated.
- Trigger a paragraph retry (mocked if necessary) and verify the event is visible in the TUI log.
- Preview a cleanup from the TUI and verify the target list is correct.

## Done Criteria

- The TUI can launch and manage preprocessing, translation, and reconstruction workflows.
- Granular translation events (paragraph level) are visible in the TUI.
- The TUI provides a functional interface for the Reset/Cleanup workflow.
- All orchestration events are correctly captured and displayed in the TUI's event log.
