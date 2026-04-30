# LLD 19b: CLI Verbosity + Rich Progress Subscriber

## Summary
Add `-v`/`-vv` CLI flags and create a convention-based EventBus subscriber that renders rich progress bars during CLI execution, providing real-time feedback for long-running pipeline sessions.

## Problem Statement
Long-running CLI commands (e.g., `translate-range` across 50 chapters) produce zero stdout feedback. The EventBus exists and pipelines emit events, but nothing reads them in CLI mode — events go only to SQLite. The TUI has visual progress but CLI users are blind.

## Technical Design

### 1. CLI Flag
Add a count option to the main CLI group or individual pipeline commands:

```python
@click.option('-v', '--verbose', count=True, help='-v for INFO, -vv for DEBUG')
```

The `verbose` count passes to `configure_logging(verbosity=verbose)`. Default (0) = WARNING only.

### 2. Module: `cli_progress.py`

**Class: `CliProgressSubscriber`**

A context manager that subscribes to `*` on `default_event_bus` and renders rich progress bars.

```python
class CliProgressSubscriber:
    def __enter__(self) -> CliProgressSubscriber: ...
    def __exit__(self, *exc) -> None: ...
```

Internally uses `rich.progress.Progress` with standard columns.

### 3. Convention-Based Auto-Discovery

The subscriber watches all events and auto-creates progress tracks based on naming patterns:

| Event pattern | Action |
|---|---|
| `{stage}_started` | Create top-level progress task for stage |
| `{stage}_completed` / `{stage}_failed` | Complete stage task |
| `{stage}.chapter_completed` | Advance chapter counter for that stage |
| `{stage}.paragraph_started` / `.paragraph_completed` | Advance block sub-bar |
| `{stage}.artifact_written` | Increment artifact counter |
| `validation_failed`, `risk_detected` | Increment warning counter |
| `*_skipped`, `*_retry` | Increment skip/retry counter |

Pattern matching uses simple string parsing:
- `event_type.endswith("_started")` → detect stage start
- `event_type.endswith("_completed")` or `"_failed")` → detect completion
- `"." in event_type` → detect sub-operations (chapter, paragraph level)

The subscriber maintains a dict of `stage_name → rich.Task` for tracking. Unknown event types are ignored (no crash, no display).

### 4. Rich Progress Layout

```
Stage          ━━━━━━━━━━━━━━━━━━━━  12/50 chapters
Blocks         ━━━━━━━━━━━━━━━━━━━━  45/48 blocks     ⚠ 3  ⊘ 1
```

Columns: `SpinnerColumn`, `TextColumn`, `BarColumn`, `TaskProgressColumn`, plus custom counter columns for warnings/skips.

### 5. Lifecycle
1. CLI command creates `with CliProgressSubscriber() as sub:` before calling pipeline.
2. Pipeline emits events → subscriber renders progress bars.
3. On `__exit__`, subscriber unsubscribes from EventBus and calls `progress.stop()`.

### 6. Verbosity Interaction
- Progress bars always render (independent of loguru level).
- `-v`: loguru INFO logs interleave with progress (rich handles this via `RichHandler` integration or loguru's stderr sink coexisting with progress).
- `-vv`: loguru DEBUG adds per-block/event detail.
- No flag: only progress bars + WARNING+ logs.

## Data Flow
1. CLI parses `-v` flag, calls `configure_logging(verbosity=N)`.
2. CLI enters `CliProgressSubscriber` context.
3. Pipeline runs, emits EventBus events.
4. Subscriber's `*` handler matches events to naming patterns.
5. Rich progress bars update in real-time.
6. On completion, subscriber unsubscribes and stops progress display.

## Out of Scope
- Adding EventBus emissions to pipelines (Task 19c).
- Modifying TUI display.
- Adding `-q`/`--quiet` flag (default verbosity=0 already acts as quiet).
- Per-stage custom renderers (convention handles all cases).
