# 8. Exit Codes & Signals

## Exit Codes

| Code | Meaning | When |
|------|---------|------|
| `0` | Success | Stage completed without errors |
| `1` | Stage failure | Stage returned failure status; check logs |
| `2` | Invalid arguments | Unknown command, bad option, or missing required argument |
| `130` | Interrupted | First Ctrl+C triggers graceful stop after current task |

## Interrupt Handling

Resemantica supports two-stage interrupt via `StopToken` (`orchestration/stop.py`):

**First Ctrl+C** — Graceful stop:
- `StopToken.requested` is set via a `threading.Event`
- Running LLM calls complete their current generation
- Pipeline code calls `raise_if_stop_requested()` at granular checkpoints, which raises `StopRequested` carrying a `checkpoint` dict for resumption
- No data loss; pipeline resumable via `rsem run resume`
- Prints: `Stopping after current task...`

**Second Ctrl+C** — Force stop:
- Sets `StopToken.force = True`
- Calls `os._exit(130)` immediately
- May leave partial artifacts; run `cleanup-apply` before resuming
- Prints: `Force stopping...`

### Platform-specific behavior

- **Windows**: Uses `SetConsoleCtrlHandler` on a dedicated handler thread (fires even during blocking I/O)
- **Unix/macOS**: Uses `signal.signal(SIGINT)` which interrupts system calls

## Retry Strategy

For transient failures (network, LLM timeout):

1. Automatic retries: configured via `llm.max_retries` (default: 2)
2. Stage retry: `rsem run retry-failed --stage <stage>` retries only failed pipeline units
3. Full rebuild: `--force` flag re-runs a stage from scratch, ignoring checkpoints
