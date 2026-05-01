# Task 29: Force Stop — Immediate Kill + Faster Graceful Stop

## Goal

Add force stop (second Ctrl+C = `os._exit(130)`) and improve graceful stop granularity from chapter-level to pass-level in sequential translation, so the process stops quickly when requested.

## Scope

In:

- **`cli.py`**: Second Ctrl+C now calls `os._exit(130)` instead of raising `KeyboardInterrupt` (which couldn't interrupt blocking I/O). First press remains graceful stop request.
- **`runner.py` (`_translate_chapter`)**: Add stop checkpoints between pass1→pass2→pass3 so graceful stop waits for 1 LLM call instead of 3.
- **`stop.py`**: Add `force: bool` field to `StopToken` so pipeline code can distinguish graceful vs force stop.

Out:

- Adding stop checkpoints to non-translation pipelines (glossary, idioms, graph, summaries, packets) — already at chapter granularity, which is fine.
- TUI force stop binding — CLI only for now.
- Any timeout-based auto-force-stop mechanism.

## Owned Files Or Modules

- `src/resemantica/cli.py` (SIGINT handler)
- `src/resemantica/orchestration/runner.py` (`_translate_chapter` checkpoints)
- `src/resemantica/orchestration/stop.py` (force flag on StopToken)

## Interfaces To Satisfy

### `cli.py` — `_with_cli_progress`

```python
def request_stop(_signum, _frame):
    if not stop_token.requested:
        stop_token.request_stop()
        print("Stopping after current task...", file=sys.stderr)
        return
    # Second press — immediate force kill
    print("Force stopping...", file=sys.stderr)
    os._exit(130)
```

Remove the `except KeyboardInterrupt` branch (no longer needed — second press terminates immediately). Keep `except StopRequested` for graceful stop path. Remove `sigint_restore` finally block (process is dead after `os._exit`).

### `stop.py` — `StopToken`

```python
@dataclass(slots=True)
class StopToken:
    _event: Event = field(default_factory=Event)
    force: bool = False
```

### `runner.py` — `_translate_chapter`

Add checkpoint calls after each pass:

| After | Checkpoint | Message |
|-------|-----------|---------|
| pass1 | `{"chapter_number": N, "pass": "pass1", "status": pass1_result}` | "Stopped after pass1 of chapter N" |
| pass2 | `{"chapter_number": N, "pass": "pass2", "status": pass2_result}` | "Stopped after pass2 of chapter N" |
| pass3 | `{"chapter_number": N, "pass": "pass3", "status": pass3_result}` | "Stopped after pass3 of chapter N" |

Keep existing before-chapter checkpoint unchanged.

## Graceful Stop Message

Update the CLI message from "Stopping after current chapter..." to "Stopping after current task..." since the granularity is now finer.

## Tests Or Smoke Checks

- Unit: `_translate_chapter` raises `StopRequested` after pass1/pass2/pass3 when token is set.
- Unit: Second Ctrl+C calls `os._exit` (mock `os._exit` to avoid actual termination).
- Unit: `StopToken.force` defaults to `False`.
- Smoke: Run `resemantica -vvv translate-range ...`, press Ctrl+C once → stops after current pass.
- Smoke: Press Ctrl+C twice → process terminates immediately (exit code 130).

## Done Criteria

- Second Ctrl+C terminates the process immediately regardless of blocking I/O.
- Graceful stop in sequential translation waits for current pass, not current chapter.
- `StopToken` carries `force` flag for downstream use.
- No changes to non-translation pipelines.
- All existing tests pass.
