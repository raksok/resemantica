# LLD 12: CLI And TUI

## Summary

Provide operator-facing command and console surfaces on top of orchestration. These surfaces display and trigger workflow behavior but do not own the behavior.

## Public Interfaces

CLI commands:

- `epub-roundtrip`
- `translate-chapter`
- `translate-range`
- `preprocess glossary-discover`
- `preprocess glossary-translate`
- `preprocess glossary-promote`
- `preprocess summaries`
- `preprocess idioms`
- `preprocess graph`
- `packets build`
- `run production`
- `run resume`
- `run cleanup-plan`
- `run cleanup-apply`
- `rebuild-epub`
- `tui`

TUI screens:

- run selection / release selection
- stage progress view
- chapter progress view
- warnings and failures view
- artifact inspection shortcuts
- cleanup workflow view

TUI layout and screen specifications: `lld-12-tui-layout.md`

## Data Flow

1. Operator invokes a CLI command or TUI action.
2. CLI validates arguments and forwards normalized requests to orchestration services.
3. TUI screens subscribe to orchestration events and read run metadata through presenters.
4. Orchestration executes workflow behavior and emits status events.
5. CLI and TUI render progress, warnings, failures, and artifact references from shared state.
6. Both surfaces expose enough status that the operator does not need to open MLflow manually.

## Validation Ownership

- CLI validates arguments and forwards normalized requests to orchestration
- TUI validates operator actions against orchestration-supported commands only
- neither surface contains duplicate stage logic

## Resume And Rerun

- resume actions call orchestration resume services instead of inferring state from local files
- rerun and cleanup actions must show the same scope and artifact targets that orchestration records
- TUI restart after process exit reloads state from run metadata and event history

## Tests

- command parsing and dispatch
- TUI presenter behavior given event stream fixtures
- visible warning/error state propagation
- resume and rerun command dispatch to orchestration services

## Out Of Scope

- alternate execution logic in UI
- custom business rules embedded in command handlers
