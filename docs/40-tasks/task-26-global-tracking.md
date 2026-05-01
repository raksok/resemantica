# Task 26: Global Observability & Event Granularity

## Milestone And Depends On

Milestone: M26

Depends on: M25, M19

## Goal

Upgrade the event tracking system from a flat publish-subscribe bus into a granularity-aware observability pipeline with standardized event taxonomy, an `ObservabilityAdapter` abstraction layer between `EventBus` and consumers, extraction-phase events, fixed MLflow tracking, and CLI verbosity extended beyond `-v`/`-vv`.

The adapter must support two modes transparently: **in-process live streaming** (pipeline launched from TUI/cli.py) and **cross-process polling** (TUI monitoring an independently launched `resemantica.cli` run via tracking DB).

## Scope

In:

- Define 5 granularity levels: `ERROR`(0), `STAGE`(1), `CHAPTER`(2), `PARAGRAPH`(3), `TOKEN`(4).
- Build `ObservabilityAdapter` abstraction with common interface:
  - `subscribe(granularity_level, callback)` — receive events at or above the requested granularity
  - `unsubscribe(granularity_level, callback)`
  - `snapshot() -> ObservabilitySnapshot` — aggregate view of recent events
  - `close()` — release resources
- Implement `LiveAdapter` backend:
  - Wraps in-process `EventBus.subscribe("*")`
  - Filters events by granularity before forwarding to consumer callbacks
  - Zero-latency push for TUI-launched pipelines
- Implement `PollAdapter` backend:
  - Reads from tracking DB + Loguru JSONL on a configurable interval
  - Produces identical `ObservabilitySnapshot` structure
  - Used when monitoring externally-launched pipeline
- Auto-select backend in TUI `ObservabilityScreen` based on whether pipeline was launched in-process (`active_action is not None`) or external.
- Standardize event type taxonomy to consistent dot-notation:
  - `{stage}.{substage}.{action}` format
  - Deprecate bare event types (`stage_started` → `orchestration.stage_started`)
  - Keep backward-compatible aliases for existing subscribers during migration
- Add chapter-level events to `extract_epub`:
  - `epub.extraction.chapter_started`
  - `epub.extraction.chapter_completed`
  - `epub.extraction.chapter_skipped`
  - `epub.extraction.completed`
- Fix MLflow tracking subscription to match actual event type strings emitted by the runner (`stage_started` not `stage.started`).
- Add automatic Loguru extra-fields binding (`chapter_number`, `stage_name`, `block_id`, `event_type`) when `emit_event()` is called, so log records carry structured context.
- Extend CLI verbosity from current clamped `0..2` to `0..4`, mapping to granularity levels.
- Update `CliProgressSubscriber` to use granularity-aware filtering instead of manual event-type pattern matching.
- Update `ObservabilityScreen` to consume `ObservabilityAdapter` instead of directly subscribing to `EventBus` and loading from DB.

Out:

- Per-token or per-subword events (no consumer requires this granularity).
- External IPC/socket transport for the adapter (single-process only for M26; cross-process uses DB polling which already works).
- Rewriting the `EventBus` internals — the publish path stays as-is.
- Adding new events to pipeline stages beyond extraction (glossary/summaries/idioms/graph/packets already emit per-chapter events; no change needed).
- Replacing the tracking DB schema.

## Owned Files Or Modules

- `src/resemantica/observability/adapter.py` — NEW: ObservabilityAdapter interface + LiveAdapter + PollAdapter
- `src/resemantica/observability/__init__.py` — NEW: exports
- `src/resemantica/observability/granularity.py` — NEW: granularity level enum + event type classification
- `src/resemantica/epub/extractor.py` — add chapter-level event emissions
- `src/resemantica/orchestration/events.py` — add backward-compatible aliases, Loguru binding hook
- `src/resemantica/cli.py` — extend verbosity to 4 levels, remove clamp
- `src/resemantica/cli_progress.py` — use granularity-aware filtering
- `src/resemantica/tracking/mlflow.py` — fix event type subscription strings
- `src/resemantica/tui/screens/observability.py` — consume ObservabilityAdapter instead of direct EventBus + DB
- `src/resemantica/tui/observability.py` — refactor into adapter-compatible shape
- `tests/observability/` — NEW: test adapter, backends, granularity filtering

## Interfaces To Satisfy

- `ObservabilityAdapter.subscribe(level, callback)` dispatches events to callback only if event granularity >= level.
- `ObservabilityAdapter.unsubscribe(level, callback)` removes subscription.
- `ObservabilityAdapter.snapshot() -> ObservabilitySnapshot` returns same shape regardless of backend.
- `ObservabilityAdapter.close()` tears down subscriptions and resources.
- `LiveAdapter` auto-subscribes to `EventBus("*")` and filters by granularity.
- `PollAdapter` tracks last-read position in tracking DB and log file to avoid duplicate events.
- TUI `ObservabilityScreen` auto-selects backend: `LiveAdapter` if `app.active_action is not None`, else `PollAdapter`.
- `emit_event()` optionally injects structured context into Loguru logger via `logger.bind()`.
- All existing event subscribers continue to receive events without code changes (backward-compatible aliases).
- CLI `-v` / `-vv` / `-vvv` / `-vvvv` map to granularity levels 1–4 respectively.

## Tests Or Smoke Checks

- Unit test granularity classification: each known event type maps to correct level.
- Unit test `LiveAdapter` delivers events at or above subscribed level.
- Unit test `LiveAdapter` filters out events below subscribed level.
- Unit test `PollAdapter` returns correct snapshot from synthetic DB/log data.
- Unit test `PollAdapter` tracks read position correctly across multiple poll cycles.
- Unit test `ObservabilityAdapter.snapshot()` returns same structure regardless of backend.
- Unit test extraction events are emitted during `extract_epub`.
- Mounted TUI test `ObservabilityScreen` switches backend based on `active_action`.
- Mounted TUI test `ObservabilityScreen` shows events from `PollAdapter` correctly.
- Unit test CLI verbosity mapping: `-v` = granularity 1, `-vv` = granularity 2, etc.
- Unit test `emit_event()` injects Loguru extra fields when configured.
- Run `uv run --with pytest pytest tests/observability tests/tui -q`.
- Run `uv run --with ruff ruff check src/resemantica/observability src/resemantica/tui`.
- Run `uv run --with mypy mypy src/resemantica/observability src/resemantica/tui`.

## Done Criteria

- `ObservabilityAdapter` interface defined with `subscribe/unsubscribe/snapshot/close`.
- `LiveAdapter` and `PollAdapter` both implemented and passing tests.
- TUI `ObservabilityScreen` auto-selects correct backend and renders events identically for both modes.
- `extract_epub` emits per-chapter events visible on TUI Ingestion screen and Observability screen.
- MLflow tracking receives events from the runner.
- Loguru structured logs carry `chapter_number`, `stage_name`, `block_id`, `event_type` when emitted alongside `emit_event()`.
- CLI supports `-vvv` and `-vvvv` mapping to paragraph and token granularity.
- Existing `CliProgressSubscriber` uses granularity filtering (behavior unchanged).
- Backward-compatible event type aliases in place so no existing subscriber breaks.
- `docs/20-lld/lld-26-global-tracking.md` is implemented and kept in sync.
