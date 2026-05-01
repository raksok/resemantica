# Task 28: CLI Display Fix — Rich/Live + Loguru Conflict

## Goal

Fix the CLI progress display where Rich progress bars and Loguru log lines both write to stderr, causing repeated lines instead of in-place updates, by routing both through a single Rich `Live` display.

## Scope

In:

- Rewrite `CliProgressSubscriber` to use Rich `Live` managing a 3-zone layout:
  - **Progress bars** (top): Rich `Progress` with spinner, description, bar, percentage (no inline counters)
  - **Status line** (middle, only non-zero counters): `skip: 3  |  warn: 1`
  - **Log panel** (bottom, scrollable, max 10 lines): last N log messages stripped to human-readable text
- Route loguru stderr output through a callable sink during `Live` lifetime, so raw text never hits stderr directly
- Restore original loguru stderr handler on exit
- Keep test backward compatibility via injected `progress` parameter (bypasses `Live` setup)

Out:

- TUI display (separate rendering system, unaffected)
- JSONL file logging (separate loguru handler, untouched)
- Changing the event emission schema or verbosity level mapping

## Owned Files Or Modules

- `src/resemantica/cli_progress.py`
- `src/resemantica/logging_config.py`
- `tests/test_cli_progress.py`

## Interfaces To Satisfy

### `logging_config.py`

```python
_stderr_config: dict[str, Any] | None  # module-level, stores stderr handler ID + level + format

def configure_logging(...) -> None:
    # unchanged except saves stderr handler config to module state

def replace_stderr_sink(sink_fn, fmt="{message}") -> None:
    """Replace stderr handler with a callable sink, keeping same level threshold."""

def restore_stderr_sink() -> None:
    """Restore stderr handler to raw sys.stderr with original level and format."""
```

### `cli_progress.py` — `CliProgressSubscriber`

- **Constructor**: accepts optional `progress` (test injection), `verbosity`, `log_lines`
- **`__enter__`**: production — creates `Progress` + `Live` + routes loguru stderr. Test mode — starts injected progress.
- **`__exit__`**: production — stops `Live`, restores loguru stderr. Test mode — stops injected progress. Unsubscribes from event bus.
- **`_render_layout()`** → `Layout`: called on each `Live` refresh, rebuilds layout with current progress/status/log
- **`_render_status()`** → `Text`: only non-zero counters
- **`_render_log_panel()`** → `Panel | Text`: last 10 log lines
- **`_log_sink(msg)`**: loguru callable, strips `[event_type] stage |` prefix, keeps `resolved_message`
- Removed: `_update_counters()`, `TextColumn("{task.fields[counters]}")` from progress columns

### Event handling (unchanged)

- Task creation/advancement/completion — same as before
- Counter tracking (`warning_count`, `skip_count`, etc.) — same as before, but no longer pushed to progress fields

## Display Layout

```
⠸ preprocess-glossary          ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   0%
⠸ preprocess-glossary.discover ━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   5%
────────────────────────────────────────────────────────────────────
skip: 3  |  warn: 1
────────────────────────────────────────────────────────────────────
Completed glossary discovery for chapter 9: 29 terms
Skipped chapter 3: no content
```

## Tests Or Smoke Checks

- Existing unit tests pass (all use injected `Progress`, bypassing `Live`/loguru routing)
- `test_cli_progress_counter_text_is_global` updated for new counter format
- Manual smoke: `resemantica -vvv preprocess glossary` shows 3-zone display with no duplicate lines
- Manual smoke: `resemantica preprocess glossary` (no flags) shows progress bars + status, no log panel
- Manual smoke: `resemantica -vvv ... | cat` (piped) degrades to raw text with no ANSI corruption

## Done Criteria

- `resemantica -vvv preprocess glossary` produces clean in-place updating 3-zone display
- No duplicate progress bar lines in terminal
- Counter/status line only shows non-zero values
- Log panel shows last 10 resolved messages (no `[event_type]` metadata prefix)
- JSONL file logging continues unaffected
- All unit tests in `test_cli_progress.py` pass
