# LLD 24: TUI Read-Only Observability Parity

## Summary

Task 24 upgrades the TUI monitoring surface so operators can inspect the same kinds of run signals that the CLI exposes through verbose logging and `CliProgressSubscriber`: counters, event progress, warnings, failures, and structured Loguru JSONL entries.

This slice is read-only. It must not add workflow launch, cancel, resume, retry, cleanup, reset, or mutation controls. The TUI remains an observer of EventBus, tracking DB, and Loguru artifacts.

## Approach

Preserve the existing screen map and upgrade screen `7` from a raw live event list into an observability screen. The implementation should keep UI rendering thin by adding presenter helpers that normalize tracking events and JSONL logs into display records.

The data flow is:

```
EventBus live events
        \
tracking DB persisted events  -> observability presenter -> Textual screen 7
        /
artifacts/logs/{run_id}.jsonl
```

The screen should render useful empty states when any source is missing. A run can have live events without a JSONL log file, persisted events without live subscriptions, or no active release/run at all.

## Public Interfaces

Screen `7` remains the observability destination:

- Keybinding: `7`
- Screen id: keep the current screen id unless a rename is mechanically low-risk
- Navigation label: `Observability` or compact `Observe`

The screen renders these sections:

```
Counters
Latest Failure
Filters
Live Events
Persisted Events
Logs
```

Verbosity levels:

| Level | Behavior |
|-------|----------|
| `normal` | counters, latest failure, warning/error events, compact recent events |
| `verbose` | normal + info-level events/logs |
| `debug` | verbose + debug logs and compact metadata/payload snippets |

Recommended keyboard controls:

| Key | Action |
|-----|--------|
| `v` | cycle verbosity: normal -> verbose -> debug -> normal |
| `s` | cycle source filter: all -> live -> persisted -> logs -> all |
| `e` | cycle severity filter: all -> warnings/errors -> errors -> all |
| `t` | cycle stage filter across observed stage names |
| `c` | cycle chapter filter across observed chapter numbers |
| `r` | refresh persisted events and logs |
| `?` | open global help |

All controls are display-only. They must not call `TUIAdapter.launch_workflow()`, cleanup functions, reset functions, or orchestration runner methods.

## Data Models

Add a small presenter module if useful:

`src/resemantica/tui/observability.py`

Suggested types:

```python
@dataclass(frozen=True)
class ObservabilityRecord:
    source: Literal["live", "persisted", "log"]
    timestamp: str
    severity: str
    stage_name: str | None
    event_type: str | None
    logger_name: str | None
    message: str
    chapter_number: int | None
    block_id: str | None
    metadata: dict[str, object]

@dataclass(frozen=True)
class ObservabilitySnapshot:
    counters: ObservabilityCounters
    latest_failure: ObservabilityRecord | None
    live_records: list[ObservabilityRecord]
    persisted_records: list[ObservabilityRecord]
    log_records: list[ObservabilityRecord]
```

Presenter helpers should be deterministic and unit-testable:

- Convert `tracking.models.Event` to `ObservabilityRecord`.
- Parse one Loguru JSONL line into `ObservabilityRecord`.
- Ignore malformed JSONL lines and count or surface them as a low-priority warning only if useful.
- Build counters from normalized records.
- Select latest failure by timestamp from records with severity `error` or event/log names containing `fail`.
- Apply verbosity and source/severity filters.

## Loguru JSONL Parsing

`logging_config.configure_logging()` writes serialized Loguru records to:

```
artifacts/logs/{run_id or "session"}.jsonl
```

For TUI run scope, read:

```
{artifact_root}/logs/{run_id}.jsonl
```

Loguru serialized rows contain a top-level JSON object with a `record` field. Extract conservatively:

- timestamp: `record.time.repr` or `record.time.timestamp`
- severity: `record.level.name`
- logger name: `record.name`
- message: `text` or `record.message`
- function/line metadata when verbosity is `debug`

If the file does not exist, render `[dim]No JSONL log file for this run yet.[/]`.

## Event Sources

Live events:

- Subscribe to `*` on the default EventBus while screen `7` is mounted.
- Keep a bounded in-memory list, e.g. latest 100 records.
- Scope to active `release_id` and `run_id`.

Persisted events:

- Load from `tracking.repo.load_events(conn, run_id=..., release_id=..., limit=...)`.
- Refresh on mount, `r`, and the existing screen refresh cadence.
- Use a bounded display list to avoid large render cost.

Deduping:

- Do not attempt complex cross-source dedupe for logs versus events.
- Deduplicate live/persisted event duplicates by a stable tuple:
  `(timestamp, event_type, stage_name, chapter_number, block_id, message)`.

## Counters

Match CLI progress intent:

| Counter | Source Rule |
|---------|-------------|
| warnings | severity `warning`, `validation_failed`, or `risk_detected` |
| failures | severity `error` or event/log name containing `failed` |
| skips | event/log name ending `_skipped` or `.chapter_skipped` |
| retries | event/log name ending `_retry`, `.retry`, or containing `retry` |
| artifacts | event/log name `artifact_written` or ending `.artifact_written` |

Render as compact text:

```
Warnings 3   Failures 1   Skips 0   Retries 2   Artifacts 14
```

## Screen Layout

Keep the screen dense and operational:

```
Observability

Counters
Warnings 0   Failures 0   Skips 0   Retries 0   Artifacts 0

Latest Failure
No failures for this run.

Filters
Verbosity: normal   Source: all   Severity: warnings/errors

Live Events
...

Persisted Events
...

Logs
...
```

Avoid nested cards or a visual redesign. Use the existing Palenight palette and `Static` widgets unless a `DataTable` materially improves scanability without lifecycle risk.

## Help Text

Update the global help modal with observability keys:

- `v` cycle verbosity on screen 7
- `s` cycle source filter on screen 7
- `e` cycle severity filter on screen 7
- `t` cycle stage filter on screen 7
- `c` cycle chapter filter on screen 7
- `r` refresh observability data on screen 7

The help text should make clear these keys are read-only filters/refresh actions.

## Tests

Presenter tests:

- Build counters from fixture events and logs.
- Select latest failure from mixed records.
- Parse representative Loguru JSONL.
- Ignore malformed JSONL line without raising.
- Apply verbosity and severity filters.

Mounted TUI tests:

- Screen `7` mounts without release/run and renders clear empty states.
- Screen `7` renders fixture persisted events for an active release/run.
- Live EventBus event scoped to the active run appears on screen `7`.
- Pressing `v` changes verbosity label without mutating run state.
- Global help includes observability keys.

Run:

- `uv run --with pytest pytest tests/tui -q`
- `uv run --with ruff ruff check src/resemantica/tui tests/tui`
- `uv run --with mypy mypy src/resemantica/tui --ignore-missing-imports`

## Assumptions

- Loguru JSONL files are append-only and may not exist for a run if logging was not configured before the run started.
- Tracking DB persisted events remain the authoritative event history.
- Live EventBus events only cover the current process lifetime.
- Read-only observability is intentionally separate from future flow-control work.
