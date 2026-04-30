# Task 19b: CLI Verbosity + Rich Progress Subscriber

## Milestone And Depends On

Milestone: M19

Depends on: M19a

## Goal
Add `-v`/`-vv` CLI flags and create a convention-based EventBus subscriber that renders rich progress bars during CLI execution.

## Scope
In:
- Add `--verbose` / `-v` count flag to CLI entry points (`cli.py`).
- Wire flag value to `configure_logging(verbosity=verbose)`.
- Create `src/resemantica/cli_progress.py` with `CliProgressSubscriber` class.
- `CliProgressSubscriber` subscribes to `*` on `default_event_bus` and auto-renders rich progress bars from event naming conventions.
- Wire `CliProgressSubscriber` as context manager in CLI commands that run pipelines.

Out:
- Adding EventBus emissions to pipelines (Task 19c).
- Modifying TUI display (TUI has its own rendering).
- Adding `-q`/`--quiet` flag (default verbosity=0 already acts as quiet).

## Owned Files Or Modules
- `src/resemantica/cli_progress.py` (new)
- `src/resemantica/cli.py` (add `-v` flag, wire subscriber)

## Interfaces To Satisfy
- `CliProgressSubscriber` context manager: subscribes on `__enter__`, unsubscribes and stops progress on `__exit__`.
- Event naming convention for auto-discovery:

| Event pattern | Action |
|---|---|
| `{stage}_started` | Create top-level stage bar |
| `{stage}_completed` / `{stage}_failed` | Complete stage bar |
| `{stage}.chapter_completed` | Advance chapter counter |
| `{stage}.paragraph_completed` | Advance block-level sub-bar |
| `{stage}.artifact_written` | Increment artifact counter badge |
| `validation_failed`, `risk_detected`, `*_skipped`, `*_retry` | Increment warning/error counter badge |

- Rich progress columns: `{SpinnerColumn}`, `{BarColumn}`, `{TaskProgressColumn(show_text=True)}`, counter badges for warnings/errors.
- Progress bars are always shown regardless of verbosity level (loguru level varies independently).

## Tests Or Smoke Checks
- `CliProgressSubscriber` creates a progress bar on receiving `*_started` event.
- Advances counter on `*.chapter_completed` event.
- Increments warning counter on `validation_failed` event.
- Increments skip counter on `*_skipped` event.
- Context manager subscribes on enter, unsubscribes on exit.
- `-v` flag sets verbosity=1, `-vv` sets verbosity=2, no flag sets 0.

## Done Criteria
- `resemantica preprocess summaries -v` shows INFO logs alongside progress bars.
- `resemantica translate-range -vv` shows DEBUG logs with per-block detail.
- `resemantica run production` (no flag) shows only progress bars and WARNING+ logs.
- `CliProgressSubscriber` auto-renders events from all pipelines without per-pipeline registration.
- Unit tests cover subscriber behavior and CLI flag wiring.
