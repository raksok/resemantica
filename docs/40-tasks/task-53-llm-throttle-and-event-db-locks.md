# Task 53: LLM Throttle And Event DB Locks

## Milestone

M53

## Depends On

M52

## Goal

Standardize per-model LLM request throttling across all runtime stages and harden tracking event persistence so concurrent workers and skipped chapters do not produce SQLite lock tracebacks.

## Scope

- Add `llm.max_concurrent_requests_per_model` with a default of `1`.
- Apply a process-local per-model semaphore to every `LLMClient.generate_text()` provider request.
- Keep same-model requests serialized by default while allowing different model names to run concurrently.
- Open `tracking.db` with WAL, SQLite timeout, and busy timeout.
- Retry transient event persistence locks with bounded backoff.
- Keep event persistence failures non-fatal for live event subscribers.

## Owned Files Or Modules

- `src/resemantica/settings.py`
- `src/resemantica/llm/client.py`
- `src/resemantica/tracking/repo.py`
- `src/resemantica/orchestration/events.py`
- LLM, settings, and tracking tests
- LLM/event persistence LLD docs

## Interfaces To Satisfy

- `[llm] max_concurrent_requests_per_model = 1`
- `LLMClient.generate_text(model_name=..., prompt=...)`
- `EventBus.publish(event)`
- `ensure_tracking_db(release_id)`
- `save_event(conn, event)`

## Tests Or Smoke Checks

- Same-model concurrent LLM requests never exceed the configured per-model limit.
- Different model names use independent throttle keys.
- LLM semaphores release after provider exceptions.
- Config parsing rejects `llm.max_concurrent_requests_per_model < 1`.
- Concurrent event emission does not raise on transient SQLite locks.
- Persistent SQLite lock failure is swallowed after bounded retries and live subscribers still receive events.
- Skipped summary chapter events remain non-fatal.
- Full pytest, ruff, mypy, and `git diff --check` pass.

## Done Criteria

- All `LLMClient.generate_text()` provider calls are protected by per-model throttling.
- Operators can raise per-model concurrency in config when their local router supports it.
- Tracking event writes tolerate normal concurrent reader/writer contention.
- Event persistence remains best-effort and cannot block live CLI/TUI subscriber delivery.
