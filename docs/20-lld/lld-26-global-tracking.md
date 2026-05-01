# LLD 26: Global Observability & Event Granularity

## Summary

The current event system has a flat `EventBus` with no granularity filtering, no extraction events, inconsistent event naming (dots vs underscores vs bare), dead MLflow tracking (subscribes to wrong event type strings), a CLI verbosity capped at 2 levels, and no abstraction layer between event producers and consumers.

Task 26 builds an `ObservabilityAdapter` layer between `EventBus` and all consumers, defines 5 granularity levels, adds extraction events, fixes MLflow, extends CLI verbosity to 4 levels, and refactors the TUI `ObservabilityScreen` to use the adapter — with transparent backend switching between in-process live streaming and cross-process DB polling.

## Architecture

### Before (current)

```
Pipeline code → emit_event()
                     ↓
                EventBus
               ┌───┴──────┐
               │          │
         DB persist   in-mem subscribers
               │     ┌───┼───────┐
               │     │   │       │
            tracking  TUI  CLI   MLflow
              DB     Obs   Prog  (broken)
```

### After (proposed)

```
Pipeline code → emit_event()
                     ↓
                EventBus
               ┌───┴──────┐
               │          │
          DB persist   ObservabilityAdapter
                       ├── LiveAdapter (in-process)
                       │     subscribe("*")
                       │     filter by granularity
                       │     push to callbacks
                       │     ┌───┼───────┐
                       │     │   │       │
                       │    TUI  CLI   MLflow
                       │    Obs  Prog  (fixed)
                       │
                       └── PollAdapter (cross-process)
                             read tracking DB + Loguru
                             aggregate into snapshot
                             push on interval
                             └── TUI Obs (external run mode)
```

## ObservabilityAdapter Interface

New module: `src/resemantica/observability/adapter.py`

```python
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class ObservabilityAdapter(Protocol):
    """Contract for consuming pipeline events at a requested granularity.

    Two backends implement this protocol:
      - LiveAdapter: in-process, subscribes to EventBus, zero-latency push.
      - PollAdapter: cross-process, reads tracking DB + Loguru files on interval.
    """

    def subscribe(self, level: int, callback: Callable[[Event], None]) -> None:
        """Register callback for events at or above `level` granularity.

        Args:
            level: Minimum granularity level (0=ERROR through 4=TOKEN).
            callback: Called with each matching Event as it becomes available.
        """

    def unsubscribe(self, level: int, callback: Callable[[Event], None]) -> None:
        """Remove a previously registered subscription."""

    def snapshot(self) -> ObservabilitySnapshot:
        """Return aggregated view of all events visible to this adapter.

        Returns the same ObservabilitySnapshot type regardless of backend,
        so consumers (TUI, CLI) render identically in both modes.
        """

    def close(self) -> None:
        """Release resources (subscriptions, file handles, timers)."""
```

## Granularity Levels

New module: `src/resemantica/observability/granularity.py`

### Level Definition

| Level | Name | Display | CLI Flag | TUI Verbosity | Events Included |
|-------|------|---------|----------|---------------|-----------------|
| 0 | `ERROR` | Errors | (default) | `errors` | Any event with severity=error |
| 1 | `STAGE` | Stage | `-v` | `warnings/errors` | Stage transitions + errors/warnings: `*.started`, `*.completed`, `*.failed` |
| 2 | `CHAPTER` | Chapter | `-vv` | `normal` | Per-chapter events: `*.chapter_started`, `*.chapter_completed`, `*.chapter_skipped` |
| 3 | `PARAGRAPH` | Paragraph | `-vvv` | `verbose` | Per-block events: `*.paragraph_started`, `*.paragraph_completed`, `*.paragraph_*` |
| 4 | `TOKEN` | Token | `-vvvv` | `debug` | All events including retries, risk detection, term discoveries: `*.retry`, `*.risk_detected`, `*.term_found`, `*.entity_extracted` |

### Event Classification Function

```python
GRANULARITY_LEVELS: list[dict[str, Any]] = [
    {"level": 0, "name": "ERROR", "severity": "error"},
    {"level": 1, "name": "STAGE", "patterns": ["started", "completed", "failed", "transition_denied", "finalized"]},
    {"level": 2, "name": "CHAPTER", "patterns": ["chapter_started", "chapter_completed", "chapter_skipped"]},
    {"level": 3, "name": "PARAGRAPH", "patterns": ["paragraph_started", "paragraph_completed", "paragraph_skipped"]},
    {"level": 4, "name": "TOKEN", "patterns": ["retry", "risk_detected", "term_found", "entity_extracted", "draft_generated", "validation_"]},
]

def classify_event_level(event: Event) -> int:
    """Return the granularity level (0-4) for a given Event."""
    # Errors are always level 0 regardless of event_type
    if event.severity == "error":
        return 0
    et = event.event_type.lower()
    for entry in reversed(GRANULARITY_LEVELS):  # highest first
        for pattern in entry["patterns"]:
            if pattern in et or et.endswith(f".{pattern}") or et == pattern:
                return entry["level"]
    return 1  # default: stage level
```

### Use by LiveAdapter

```python
class LiveAdapter:
    def __init__(self):
        self._subscriptions: dict[int, list[Callable]] = defaultdict(list)
        subscribe("*", self._on_event)

    def subscribe(self, level: int, callback: Callable) -> None:
        self._subscriptions[level].append(callback)

    def _on_event(self, event: Event) -> None:
        event_level = classify_event_level(event)
        for sub_level, callbacks in self._subscriptions.items():
            if event_level >= sub_level:
                for cb in callbacks:
                    try:
                        cb(event)
                    except Exception:
                        pass

    def snapshot(self) -> ObservabilitySnapshot:
        # delegates to existing build_snapshot() from tui/observability.py
        ...
```

## Backend: LiveAdapter (In-Process)

**File**: `src/resemantica/observability/adapter.py`

### Lifecycle

1. `__init__`: subscribes to `EventBus("*")` via the module-level `subscribe` function.
2. `_on_event`: classifies event granularity via `classify_event_level()`, then dispatches to matching subscriptions.
3. `subscribe(level, callback)`: appends callback to `self._subscriptions[level]`.
4. `unsubscribe(level, callback)`: removes callback from `self._subscriptions[level]`.
5. `snapshot()`: calls `build_snapshot()` from `resemantica.tui.observability` with the adapter's internal event buffer.
6. `close()`: calls `unsubscribe("*", self._on_event)` to detach from EventBus.

### Internal Event Buffer

The `LiveAdapter` maintains a deque of recent events (max 1000) for `snapshot()` calls:

```python
from collections import deque

self._buffer: deque[Event] = deque(maxlen=1000)
```

In `_on_event`, after dispatching to subscriptions, also append to `self._buffer`.

### snapshot() Implementation

```python
def snapshot(self) -> ObservabilitySnapshot:
    return build_snapshot(
        live_events=list(self._buffer),
        persisted_events=[],  # LiveAdapter doesn't re-read from DB
        log_records=[],       # LiveAdapter doesn't re-read from log files
    )
```

The TUI's `ObservabilityScreen` additionally calls `self._load_recent_run_events()` and `load_log_records()` for the "Persisted" and "Logs" sections, layering adapter live events on top.

## Backend: PollAdapter (Cross-Process)

**File**: `src/resemantica/observability/adapter.py`

### Lifecycle

1. `__init__(release_id, run_id, poll_interval=2.0)`:
   - Stores release_id and run_id.
   - Tracks last-read position: `_last_event_id` (UUID string) and `_last_log_position` (file byte offset).
   - Does NOT subscribe to EventBus.
2. `subscribe(level, callback)`: stores callback for push on poll cycle (uses `call_after_refresh` in TUI context).
3. `snapshot()`: reads tracking DB from `_last_event_id` forward, reads log file from `_last_log_position` forward, aggregates, returns `ObservabilitySnapshot`. Updates read positions.
4. `close()`: no-op (no subscriptions to clean up).

### Position Tracking

```python
class PollAdapter:
    def __init__(self, release_id: str, run_id: str, poll_interval: float = 2.0):
        self._release_id = release_id
        self._run_id = run_id
        self._poll_interval = poll_interval
        self._last_event_id: str | None = None  # UUID of last processed event
        self._last_log_offset: int = 0  # byte offset in JSONL file
        self._subscriptions: dict[int, list[Callable]] = defaultdict(list)
        self._buffer: deque[Event] = deque(maxlen=1000)
```

### snapshot() Implementation

```python
def snapshot(self) -> ObservabilitySnapshot:
    events: list[Event] = []
    conn = ensure_tracking_db(self._release_id)
    try:
        # Load events after last seen ID
        cursor = conn.execute(
            "SELECT * FROM events WHERE run_id = ? AND release_id = ? ORDER BY event_time",
            (self._run_id, self._release_id),
        )
        found_last = self._last_event_id is None
        for row in cursor:
            if not found_last:
                if row["event_id"] == self._last_event_id:
                    found_last = True
                continue
            events.append(event_from_row(row))
        if events:
            self._last_event_id = events[-1].event_id
    finally:
        conn.close()

    log_records = []
    log_path = self._log_path()
    if log_path and log_path.exists():
        with log_path.open("r", encoding="utf-8") as f:
            f.seek(self._last_log_offset)
            for line in f:
                record = parse_loguru_jsonl_line(line)
                if record:
                    log_records.append(record)
            self._last_log_offset = f.tell()

    for event in events:
        self._buffer.append(event)

    return build_snapshot(
        live_events=[],
        persisted_events=events,
        log_records=log_records,
    )
```

Note: `PollAdapter` returns events as "persisted" (source=`"persisted"`) since they came from DB. This matches the TUI's expectation for the "Persisted Events" section.

## Backend Auto-Selection in TUI

In `ObservabilityScreen._refresh_observability()`, replace the current dual-source loading (EventBus subscription + DB loading) with adapter-based loading:

```python
class ObservabilityScreen(BaseScreen):
    def on_mount(self) -> None:
        self._adapter: ObservabilityAdapter | None = None
        super().on_mount()

    def _ensure_adapter(self) -> ObservabilityAdapter:
        if self._adapter is not None:
            return self._adapter

        active = getattr(self.app, "active_action", None)
        if active is not None:
            # Pipeline was launched from TUI → use live streaming
            from resemantica.observability.adapter import LiveAdapter
            adapter = LiveAdapter()
        else:
            # Pipeline running externally → use DB polling
            rid = self._get_release_id()
            rn = self._get_run_id()
            if rid and rn:
                from resemantica.observability.adapter import PollAdapter
                adapter = PollAdapter(release_id=rid, run_id=rn)
            else:
                # No run at all → use a no-op adapter
                from resemantica.observability.adapter import NullAdapter
                adapter = NullAdapter()

        self._adapter = adapter
        self._adapter.subscribe(0, self._on_adapter_event)  # receive all levels
        return self._adapter

    def _refresh_observability(self) -> None:
        adapter = self._ensure_adapter()
        snapshot = adapter.snapshot()
        # Also load persisted events for the "Persisted" section
        persisted_events = self._load_recent_run_events(limit=100)
        # Also load log records
        log_path = self._log_path()
        log_records = load_log_records(log_path, limit=100) if log_path else []

        # Merge: adapter snapshot gives live events, DB gives persisted, files give logs
        merged = ObservabilitySnapshot(
            counters=build_counters([*snapshot.live_records, *persisted_records, *log_records]),
            latest_failure=select_latest_failure([*snapshot.live_records, *persisted_records, *log_records]),
            live_records=snapshot.live_records,
            persisted_records=[event_to_record(e, source="persisted") for e in persisted_events],
            log_records=log_records,
        )
        self._render_observability(merged)
        self._render_warnings(persisted_events)
```

## Event Taxonomy Standardization

### Current State (inconsistent)

| Where | Example | Format |
|-------|---------|--------|
| Runner | `stage_started`, `stage_completed`, `stage_failed` | Underscore |
| Runner | `stage.transition_denied` | Dot |
| Runner | `run_finalized` | Bare |
| Glossary | `preprocess-glossary.discover.term_found` | Dot-namespaced |
| Glossary | `preprocess-glossary.discover.chapter_started` | Dot-namespaced |
| Translation | `paragraph_started`, `paragraph_completed` | Bare |
| Translation | `risk_detected`, `validation_failed` | Bare |
| Resume | `resume.started`, `resume.completed`, `resume.failed` | Dot-namespaced |
| Cleanup | `cleanup.plan_created`, `cleanup.apply_failed` | Dot-namespaced |

### Standardize To: `{prefix}.{action}`

New events follow `{stage}.{granularity}_{action}`:

| Current | Standardized | Alias kept for? |
|---------|-------------|-----------------|
| `stage_started` | `orchestration.stage_started` | CliProgress, TUI (1 release) |
| `stage_completed` | `orchestration.stage_completed` | CliProgress, TUI (1 release) |
| `stage_failed` | `orchestration.stage_failed` | CliProgress, TUI (1 release) |
| `run_finalized` | `orchestration.run_finalized` | — |
| `paragraph_started` | `translate.paragraph_started` | CliProgress, TUI (1 release) |
| `paragraph_completed` | `translate.paragraph_completed` | CliProgress, TUI (1 release) |
| `risk_detected` | `translate.risk_detected` | TUI (1 release) |

**Migration strategy**: `emit_event()` publishes under BOTH the old and new event type for one release cycle. After M27, remove the old type.

```python
def emit_event(..., event_type: str) -> Event:
    new_type = _standardized_type(event_type)
    types_to_emit = [event_type]
    if new_type and new_type != event_type:
        types_to_emit.append(new_type)
    for et in types_to_emit:
        event = Event(event_type=et, ...)
        bus.publish(event)
    return event
```

## Extraction Events

Add to `src/resemantica/epub/extractor.py`:

After the chapter parsing loop, emit events:

```python
from resemantica.orchestration.events import emit_event

def extract_epub(input_path, release_id, config=None, project_root=None, run_id="epub-extract"):
    # ... existing setup ...

    chapter_results = []
    for chapter_doc in chapter_docs:
        emit_event(
            run_id=run_id,
            release_id=release_id,
            event_type="epub.extraction.chapter_started",
            stage_name="epub-extract",
            chapter_number=chapter_doc.chapter_number,
            message=f"Extracting chapter {chapter_doc.chapter_number}",
        )
        try:
            result = parse_chapter(chapter_doc, ...)
            chapter_results.append(result)
            emit_event(
                run_id=run_id,
                release_id=release_id,
                event_type="epub.extraction.chapter_completed",
                stage_name="epub-extract",
                chapter_number=chapter_doc.chapter_number,
                message=f"Extracted chapter {chapter_doc.chapter_number}",
            )
        except Exception as exc:
            emit_event(
                run_id=run_id,
                release_id=release_id,
                event_type="epub.extraction.chapter_skipped",
                stage_name="epub-extract",
                chapter_number=chapter_doc.chapter_number,
                severity="warning",
                message=f"Skipped chapter {chapter_doc.chapter_number}: {exc}",
            )

    emit_event(
        run_id=run_id,
        release_id=release_id,
        event_type="epub.extraction.completed",
        stage_name="epub-extract",
        message=f"Extraction completed: {len(chapter_results)} chapters",
    )
    # ... existing return ...
```

## CLI Verbosity Extension

### Current (`cli.py`)

```python
parser.add_argument("-v", "--verbose", action="count", default=0)
# clamped to max 2 in _configure_cli_logging()
```

### New

```python
parser.add_argument("-v", "--verbose", action="count", default=0)

# No clamp — allow 0-4
# In _configure_cli_logging():
effective = verbosity  # remove min(max(verbosity, 0), 2)
console_levels = {0: "WARNING", 1: "INFO", 2: "INFO", 3: "DEBUG", 4: "DEBUG"}
```

### Mapping

| CLI | Granularity | Log Level | CliProgress shows |
|-----|-------------|-----------|-------------------|
| (none) | 0 — ERROR | WARNING | Errors only |
| `-v` | 1 — STAGE | INFO | Stage transitions |
| `-vv` | 2 — CHAPTER | INFO | Stage + chapter progress |
| `-vvv` | 3 — PARAGRAPH | DEBUG | Stage + chapter + paragraph |
| `-vvvv` | 4 — TOKEN | DEBUG | Everything |

### CliProgressSubscriber Granularity Filter

Replace the manual event-type pattern matching with a granularity filter:

```python
class CliProgressSubscriber:
    def __init__(self, verbosity: int = 1):
        self._level = verbosity  # granularity level from CLI -v count
        subscribe("*", self._on_event)

    def _on_event(self, event: Event) -> None:
        from resemantica.observability.granularity import classify_event_level
        if classify_event_level(event) >= self._level:
            self._process(event)
```

## MLflow Fix

### Current (`tracking/mlflow.py`)

Subscribes to `"stage.started"`, `"stage.completed"`, `"stage.failed"` — which are NEVER emitted.

### New

```python
subscribe("orchestration.stage_started", ...)
subscribe("orchestration.stage_completed", ...)
subscribe("orchestration.stage_failed", ...)
```

Also keep the existing aliases `"stage_started"`/`"stage_completed"`/`"stage_failed"` through the backward-compatible alias mechanism.

## Loguru Structured Logging Integration

### Current

No automatic binding of event fields to Loguru context. `parse_loguru_jsonl_line()` in `tui/observability.py` tries to extract `extra.chapter_number`, `extra.stage_name`, etc., but they're rarely present.

### New

In `emit_event()`, add a hook to bind structured context to the Loguru logger:

```python
def emit_event(..., chapter_number=None, block_id=None, ...) -> Event:
    # ... existing event creation and publishing ...

    # Auto-bind to Loguru if logger is configured
    try:
        logger.bind(
            event_type=event.event_type,
            stage_name=event.stage_name,
            chapter_number=event.chapter_number,
            block_id=event.block_id,
            severity=event.severity,
            run_id=event.run_id,
            release_id=event.release_id,
        )
    except Exception:
        pass  # logger might not be configured yet

    return event
```

This uses `logger.bind()` which returns a child logger with bound extra fields. The bindings persist for subsequent log calls from the same thread. To avoid accidental cross-talk, use a context manager or call `logger.bind()` only for the duration of the emit:

Actually, better: use `logger.patch()` to inject a record decorator:

No — simplest is to just emit a structured loguru log message alongside the event:

```python
logger.log(
    _severity_to_loguru(event.severity),
    "[{event_type}] {stage_name} | {message}",
    event_type=event.event_type,
    stage_name=event.stage_name,
    message=event.message,
    chapter_number=event.chapter_number,
    block_id=event.block_id,
    run_id=event.run_id,
    release_id=event.release_id,
)
```

Using Loguru's `{extra}` formatting ensures these fields appear in the JSONL serialized output. This is the simplest approach — one log call per event, matching severity, with all structured fields as extra.

## File Manifest

| File | Action |
|------|--------|
| `src/resemantica/observability/__init__.py` | NEW — empty or re-export |
| `src/resemantica/observability/adapter.py` | NEW — ObservabilityAdapter protocol, LiveAdapter, PollAdapter, NullAdapter |
| `src/resemantica/observability/granularity.py` | NEW — classify_event_level(), GRANULARITY_LEVELS |
| `src/resemantica/epub/extractor.py` | MODIFY — add chapter-level events to extract_epub |
| `src/resemantica/orchestration/events.py` | MODIFY — add backward-compatible aliases, Loguru structured logging in emit_event() |
| `src/resemantica/cli.py` | MODIFY — extend verbosity to 4 levels, remove clamp |
| `src/resemantica/cli_progress.py` | MODIFY — use granularity filter instead of manual pattern matching |
| `src/resemantica/tracking/mlflow.py` | MODIFY — fix event type subscription strings |
| `src/resemantica/tui/screens/observability.py` | MODIFY — consume ObservabilityAdapter with auto-select backend |
| `src/resemantica/tui/observability.py` | MODIFY — ensure build_snapshot() works with adapter event buffers |

Not modified (no changes needed): `screens/ingestion.py`, `screens/preprocessing.py`, `screens/translation.py` — these consume `build_snapshot()` from `launch_control.py` (run state), not from `observability.py` (event stream). The extraction chapter events flow through the adapter automatically once the adapter is in place.

## Implementation Order

### Phase 1: Foundation

1. `granularity.py` — classify_event_level(), GRANULARITY_LEVELS
2. `adapter.py` — ObservabilityAdapter protocol stub, NullAdapter
3. `adapter.py` — LiveAdapter implementation
4. Tests: granularity classification + LiveAdapter

### Phase 2: Extraction Events

5. `extractor.py` — add chapter-level event emissions to extract_epub
6. Tests: extraction events emitted correctly

### Phase 3: Backward Compat + Loguru

7. `events.py` — add backward-compatible aliases for standardized event types
8. `events.py` — add Loguru structured logging in emit_event()
9. Tests: alias mechanism + Loguru bindings

### Phase 4: MLflow + CLI

10. `mlflow.py` — fix event type subscription strings to match runner
11. `cli.py` — extend verbosity to 4 levels, remove clamp
12. `cli_progress.py` — use granularity filter
13. Tests: CLI verbosity mapping

### Phase 5: PollAdapter + TUI

14. `adapter.py` — PollAdapter implementation
15. `screens/observability.py` — refactor to use ObservabilityAdapter with auto-select
16. Tests: PollAdapter + TUI backend switching

### Phase 6: Verify

17. `ruff check`, `mypy`, `pytest`

## Tests

### Granularity Tests

- `test_classify_stage_level()` — stage_started → level 1, stage_completed → level 1
- `test_classify_chapter_level()` — preprocess-glossary.discover.chapter_started → level 2
- `test_classify_paragraph_level()` — paragraph_completed → level 3
- `test_classify_token_level()` — risk_detected → level 4, term_found → level 4
- `test_classify_error()` — any event with severity=error → level 0 regardless of type
- `test_classify_unknown()` — unknown event type → level 1 (default)

### LiveAdapter Tests

- `test_live_delivers_at_level()` — subscribe(2) receives chapter and paragraph events
- `test_live_filters_below_level()` — subscribe(2) does NOT receive stage-only events
- `test_live_multiple_subscribers()` — different levels each get correct events
- `test_live_snapshot_returns_events()` — snapshot contains buffered events
- `test_live_close_stops_delivery()` — after close, no events delivered

### PollAdapter Tests

- `test_poll_returns_persisted_events()` — snapshot returns events from synthetic DB
- `test_poll_position_tracking()` — second call starts from last event
- `test_poll_log_position_tracking()` — second call starts from last byte offset
- `test_poll_empty_db()` — snapshot with no events returns empty snapshot

### Extraction Event Tests

- `test_extraction_emits_chapter_events()` — extract_epub emits chapter_started/chapter_completed for each chapter
- `test_extraction_emits_completed()` — extract_epub emits epub.extraction.completed at end

### CLI Verbosity Tests

- `test_verbosity_0()` — default → granularity 0, console level WARNING
- `test_verbosity_1()` — -v → granularity 1, console level INFO
- `test_verbosity_2()` — -vv → granularity 2, console level INFO
- `test_verbosity_3()` — -vvv → granularity 3, console level DEBUG
- `test_verbosity_4()` — -vvvv → granularity 4, console level DEBUG

### MLflow Tests

- `test_mlflow_subscribes_orchestration_events()` — mlflow module subscribes to orchestration.stage_started/completed/failed
- `test_mlflow_receives_events()` — when runner emits stage_started, mlflow callback fires

### TUI Adapter Tests

- `test_auto_select_live()` — when app.active_action is set, adapter is LiveAdapter
- `test_auto_select_poll()` — when app.active_action is None, adapter is PollAdapter
- `test_observability_renders_live_adapter()` — mounted test: events show in live section
- `test_observability_renders_poll_adapter()` — mounted test: events show in persisted section

## Decision Log

| Decision | Alternatives | Rationale |
|----------|-------------|-----------|
| Protocol-based adapter interface (not ABC) | ABC, abstract base class | Protocol is duck-typed, no required inheritance; easier to test with mocks |
| Granularity levels 0-4 (int) | Enum, string | Simpler comparison (`>=`), easier CLI mapping, no import needed for consumers |
| classify_event_level() uses substring matching | Regex, explicit list | Suffix/prefix matching is sufficient for current event types; regex would be over-engineering |
| Backward-compatible aliases for 1 release | Breaking change, no migration | Prevents breaking existing subscribers during co-development of M26 |
| PollAdapter reads full DB table each poll (not incremental) | WAL-mode incremental read | Simpler implementation; with index and `ORDER BY event_time`, performance is acceptable for M26 |
| Loguru structured logging via logger.log() call in emit_event() | logger.bind() context manager | Simpler; one call per event, no state leakage between threads |
| Adapter lives in new `observability/` package | Put in `tui/`, put in `orchestration/` | Used by both CLI and TUI; should not be in either UI layer |
| NullAdapter for no-release/no-run state | Return empty snapshot directly | Consistent code path: always go through adapter interface |