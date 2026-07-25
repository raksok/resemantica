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
- No new LLM task is admitted after the stop is observed
- Running LLM tasks complete and persist their current durable block, batch, candidate, vote, phase, or chapter unit
- Executor work that has not started is canceled; active work is drained
- Pipeline code raises `StopRequested` with a durable checkpoint and interrupt report
- Review/promote commands for glossary and idioms use the same tokenized path and poll between DB reads, validation, durable writes, and artifact writes
- No data loss; pipeline resumable via `uv run rsem run resume`
- Prints a final report containing completed, drained, and canceled counts and the resume boundary
- Initial signal message: `Stopping after current task...`

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
2. Stage retry: `uv run rsem run retry-failed --stage <stage>` retries only failed pipeline units
3. Full rebuild: `--force` flag re-runs a stage from scratch, ignoring checkpoints
