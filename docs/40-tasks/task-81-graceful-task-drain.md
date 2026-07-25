# Task 81: Graceful Task-Level Drain And Exit

## Milestone

M81

## Depends On

M80

## Goal

Make the first stop request finish and persist active LLM work, cancel queued work, report the durable resume boundary, and exit cleanly without waiting for an entire chapter or eagerly submitted phase.

## Scope

- Use bounded rolling submission for Pass 2, summary, and continuity executors.
- Limit worker admission to the effective per-model concurrency.
- Persist partial Pass 1 and Pass 2 artifacts at block/work-unit boundaries.
- Keep sequential LLM loops cooperative at their existing durable candidate, vote, batch, block, and chapter boundaries.
- Standardize interrupt reports in stopped results, events, run state, CLI output, and TUI notifications.
- Wire `retry-failed` to the shared stop token.
- Keep the second Ctrl+C immediate force-exit behavior.

## Interfaces To Satisfy

- `LLMClient.concurrency_limit(model_name) -> int` returns the effective model or throttle-group limit.
- `run_interruptible_pool(...) -> DrainResult` admits a bounded active window, drains active futures, and counts canceled work.
- `StopRequested.interrupt_report` optionally carries an `InterruptReport`.
- `execute_retry_failed(..., stop_token=None)` forwards the token to retried stages.
- Stopped Pass 1 and Pass 2 artifacts remain reusable without `--force`.

## Decision Log

- Drain every request already executing at stop time; do not attempt unsafe transport-level cancellation.
- Treat work waiting in an application executor or model-throttle queue as queued, not active.
- Stop at the smallest durable pipeline unit rather than inside an internal retry sequence.
- Keep reports compact by storing counts and resume boundaries instead of every canceled identifier.
- Add no timeout, configuration switch, or database migration.

## Tests Or Smoke Checks

- Deterministic drain tests use thread events rather than sleeps.
- Translation tests cover partial Pass 1 and Pass 2 persistence and reuse.
- Summary and continuity concurrency tests retain ordered checkpoint behavior.
- Orchestration tests cover stopped events, run-state reports, and interruptible retry-failed.
- CLI and TUI tests cover final reports and stop wording.

## Done Criteria

- No queued LLM unit starts after the first stop request is observed.
- Active units finish and their usable output is durably saved.
- Graceful stops emit `.stopped`, never `.failed`.
- CLI returns 130 after printing the interrupt report.
- TUI returns to idle and reports drained/canceled counts.
- Normal resume reuses completed work without `--force`.
