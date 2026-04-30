# LLD 19: TUI Completion And Reconstruction Smoke Validation

## Summary

Task 19 finishes the known gaps left after the Task 18 operator-console implementation. The TUI already has an adapter, event bus, event log, and reset preview path. This slice adds launch controls for preprocessing and translation, replaces placeholder progress rendering with run-derived state, and records a completed-run reconstruction smoke result.

## Public Interfaces

TUI:

- Preprocessing screen launch control for `TUIAdapter.launch_workflow("preprocessing", ...)`
- Translation screen launch control for `TUIAdapter.launch_workflow("translation", ...)`
- Chapter spine renderer that accepts release/run-derived progress
- Translation progress renderer that accepts persisted or live paragraph/block events

CLI smoke path:

- `uv run python -m resemantica.cli rebuild-epub --release <id> --run-id <id>`

## TUI Launch Controls

Preprocessing and translation screens should remain thin UI controllers:

- read `release_id`, `run_id`, and `config_path` from the app
- construct `TUIAdapter`
- call `launch_workflow()` with explicit workflow names
- render immediate success/failure feedback from the returned stage result
- never call lower-level pipeline functions directly

If `release_id` or `run_id` is missing, controls must render a clear disabled/error state rather than starting a workflow.

## Run-Derived Progress

Chapter spine:

- Prefer extracted chapter files under the release artifact tree for chapter count.
- Use run checkpoints and events to mark chapters as completed, active, failed, or pending.
- Fall back to a small empty-state message when no release/run data exists.
- Do not render a fixed `1..20` placeholder list when chapter data exists.

Translation screen:

- Load recent paragraph, validation, risk, artifact, and chapter events for the active run.
- Group or render events by chapter and block where possible.
- Show empty-state copy only when no active run or no relevant progress data exists.
- Preserve live event subscription behavior from Task 18.

## Reconstruction Smoke Validation

The implementation should document a local smoke result after attempting the completed-run reconstruction path:

- release/run IDs used
- command executed
- generated EPUB path, if successful
- validation report path and status
- whether `epubcheck` ran or was skipped because the executable/artifact was unavailable

This task must not add network-only requirements. If no completed local run exists, record the smoke as blocked with the missing artifact paths.

## Tests

- TUI preprocessing launch button delegates to `TUIAdapter.launch_workflow("preprocessing")`.
- TUI translation launch button delegates to `TUIAdapter.launch_workflow("translation")`.
- Missing release/run context prevents workflow launch.
- Chapter spine renderer uses extracted chapter count and event/checkpoint statuses.
- Translation progress renderer displays paragraph/block events and removes placeholder copy.
- Existing event log and reset preview tests continue to pass.

Run:

- `uv run --with pytest pytest tests/tui -q`
- `uv run --with ruff ruff check src tests`
- `uv run --with mypy mypy src/resemantica`

## Assumptions

- Task 19 does not alter orchestration semantics; it consumes existing `OrchestrationRunner` and `EventBus` behavior.
- The TUI remains function-first; visual redesign is out of scope.
- EPUB smoke validation uses local artifacts only and records unavailable external tools as skipped, not failed.
