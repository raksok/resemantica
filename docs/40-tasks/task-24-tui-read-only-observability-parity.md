# Task 24: TUI Read-Only Observability Parity

## Milestone And Depends On

Milestone: M24

Depends on: M23, M19

## Goal

Upgrade the TUI's monitoring surface to provide CLI-level observability for active runs without adding new flow-control actions. Operators should be able to inspect run progress, warnings, failures, persisted events, and Loguru JSONL logs from the TUI at roughly the same level of detail available through verbose CLI execution.

## Scope

In:

- Add read-only TUI observability presenters for event counters, latest failure, persisted tracking events, live EventBus events, and Loguru JSONL log entries.
- Upgrade screen `7` from a raw event stream into an observability screen while preserving the `7` keybinding and existing navigation metadata.
- Add a TUI verbosity mode with `normal`, `verbose`, and `debug` display levels.
- Add keyboard-only filters for severity, source, stage text, and chapter number where the existing Textual widgets make this practical.
- Show CLI-style counters for warnings, failures, skips, retries, and artifacts.
- Show latest failure context with timestamp, stage, event type or logger name, message, chapter, and block when available.
- Read persisted tracking events from the active release/run and combine them with live in-process EventBus events without duplicating identical entries.
- Read Loguru JSONL entries from `artifacts/logs/{run_id}.jsonl` when the file exists.
- Update help text to mention observability keys.
- Add tests for presenter logic and mounted screen behavior.
- Update `lld-24-tui-read-only-observability-parity.md` to stay in sync.

Out:

- Starting, stopping, pausing, canceling, resuming, or retrying workflows.
- Adding production launch controls.
- Editing config, release id, run id, or chapter ranges from the TUI.
- Changing Loguru handler behavior or CLI verbosity behavior.
- Adding log rotation, retention, external log shipping, or MLflow UI integration.
- Replacing the TUI's visual design or screen map.

## Owned Files Or Modules

- `src/resemantica/tui/screens/event_log.py`
- `src/resemantica/tui/navigation.py`
- `src/resemantica/tui/screens/help.py`
- `src/resemantica/tui/palenight.tcss`
- `src/resemantica/tui/observability.py` (new, if presenter extraction is useful)
- `tests/tui/`

## Interfaces To Satisfy

- Screen `7` remains reachable with key `7` and is labeled as the observability surface.
- Observability screen renders:
  - counters for warnings, failures, skips, retries, and artifacts
  - latest failure panel
  - live events
  - persisted tracking events
  - Loguru JSONL entries when available
- Verbosity levels control display density:
  - `normal`: counters, latest failure, recent warnings/errors, compact recent events
  - `verbose`: include info-level events and log entries
  - `debug`: include debug log entries and detailed metadata snippets
- Filters are keyboard-only and include source, severity, stage, and chapter controls.
- Missing release/run/log file states render clear empty states rather than errors.
- Read-only behavior is preserved: no new screen action may launch, mutate, reset, delete, retry, or resume work.

## Tests Or Smoke Checks

- Unit test event/log presenter builds counters from mixed tracking events and Loguru JSONL entries.
- Unit test latest failure prefers newest error/failure event or log entry.
- Unit test verbosity filtering hides debug content in normal/verbose modes and shows it in debug mode.
- Unit test missing Loguru JSONL path returns an empty log list without raising.
- Mounted TUI test opens screen `7` and verifies counters and empty states render without release/run.
- Mounted TUI test with fixture release/run data verifies persisted events render on screen `7`.
- Mounted TUI test verifies help includes the observability keys.
- Run `uv run --with pytest pytest tests/tui -q`.
- Run `uv run --with ruff ruff check src/resemantica/tui tests/tui`.
- Run `uv run --with mypy mypy src/resemantica/tui --ignore-missing-imports`.

## Done Criteria

- TUI screen `7` provides read-only observability parity with the CLI's progress/logging intent.
- Operators can inspect counters, latest failure, recent persisted events, live events, and run JSONL logs from the TUI.
- Verbosity controls display density without changing run behavior.
- Missing or incomplete observability inputs degrade to clear empty states.
- Tests cover presenter behavior and mounted TUI behavior.
- `docs/20-lld/lld-24-tui-read-only-observability-parity.md` is implemented and kept in sync.
