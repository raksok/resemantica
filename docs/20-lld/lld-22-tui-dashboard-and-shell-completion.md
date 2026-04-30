# LLD 22: TUI Dashboard And Shell Completion

## Summary

Task 22 completes the shared shell widgets and dashboard screen that Task 21 left as placeholders. The header bar, footer bar, pulse bar sparkline, and dashboard quick-stats panel all consume run state and persisted events to render live data instead of static or empty content.

## Public Interfaces

Shell (BaseScreen):

- Header chapter progress: `Ch N/M` derived from run checkpoint and chapter manifest
- Header pass indicator: `PASS 1`, `PASS 2`, `PASS 3`, `IDLE`, `PREPROCESS` derived from run state `stage_name`
- Header pulse bar: 30-char ASCII sparkline of blocks/min from `paragraph_completed` events in a sliding window
- Footer block progress: `N/M blocks` from run checkpoint
- Footer warning count: count of events with `severity = "warning"`
- Footer failure count: count of events with `severity = "error"`
- Footer elapsed time: `H:MM:SS` from `state.started_at`

Dashboard:

- Quick stats panel: aggregate glossary, idiom, entity, and retry counts from persisted events

## Data Sources

All data comes from the tracking DB or the chapter manifest. No new repo functions are needed.

| Widget | Query |
|--------|-------|
| Chapter progress `Ch N/M` | `load_run_state()` checkpoint for current chapter index; `list_extracted_chapters()` for total M |
| Pass indicator | `state.stage_name` mapped to pass label |
| Pulse bar sparkline | `load_events(conn, run_id, limit=200)` filtered to `event_type` containing `paragraph_completed`, bucketed into time windows |
| Block progress `N/M` | `state.checkpoint` block_index and total |
| Warning count | `load_events()` filtered `severity = "warning"`, counted |
| Failure count | `load_events()` filtered `severity = "error"`, counted |
| Elapsed time | `state.started_at` delta to now |
| Quick stats glossary | Events with `event_type` containing `glossary` and `locked` or `promoted` |
| Quick stats idioms | Events with `event_type` containing `idiom` and `approved` |
| Quick stats entities | Events with `event_type` containing `graph` and `entity` |
| Quick stats retries | Events with `event_type` containing `retry` |
| Quick stats avg risk | Events with `event_type` containing `risk_detected`, average of `payload.risk_score` |

## Pulse Bar Sparkline

The sparkline is a 30-character ASCII bar showing blocks translated per minute over the last N minutes:

- Collect `paragraph_completed` events for the active run from the tracking DB.
- Bucket events into 30 equal time windows covering the run duration (or last 30 minutes if the run is long).
- Each bucket maps to one character: `▁▂▃▄▅▆▇█` (8 levels from 0 to max).
- Idle (no events, no active run): flat `▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁` in `comment`.
- Active: sparkline in `cyan`.
- Error/retry spike (any bucket has a retry event): that character in `red`.
- Update every 5 seconds via the existing `_refresh_all` interval (currently 3s; the spec says 5s for pulse).

## Stage-To-Pass Mapping

| `stage_name` | Pass Indicator | Color |
|---------------|---------------|-------|
| `preprocess-*`, `packets-build` | `PREPROCESS` | `comment` |
| `translate-chapter` or `translate-range` | `PASS 1` | `cyan` |
| `translate-pass2` or stage containing `pass2` | `PASS 2` | `cyan` |
| `translate-pass3` or stage containing `pass3` | `PASS 3` | `cyan` |
| `epub-rebuild` | `REBUILD` | `green` |
| Any completed or no active run | `IDLE` | `comment` |

## Quick Stats Rendering

Replace the current placeholder with event-derived counts:

```
  Quick Stats
  Glossary     {glossary_locked} locked
  Idioms       {idiom_approved} policies
  Entities     {entity_confirmed} confirmed
  Retries      {retry_total} total
  Avg risk     {avg_risk:.2f}
```

All counts come from `load_events()` filtered by event type patterns. No direct repo queries to glossary/idiom/graph subsystems.

## Tests

- Header renders `Ch N/M` from manifest count and checkpoint chapter index.
- Header renders correct pass indicator from each stage name.
- Pulse bar sparkline produces 30 chars from a fixture event list.
- Pulse bar colors: `comment` when idle, `cyan` when active, `red` on retry spike.
- Footer renders block count, warning count, failure count, and elapsed time.
- Footer elapsed time is empty when no run is active.
- Quick stats renders counts from fixture events.
- Quick stats renders empty-state message when no events exist.

Run:

- `uv run --with pytest pytest tests/tui -q`
- `uv run --with ruff ruff check src tests`
- `uv run --with mypy mypy src/resemantica`

## Assumptions

- Task 22 does not add new tracking DB tables or columns. All data comes from existing event and run_state tables.
- The pulse bar uses persisted events only (no live subscriber), matching the polling refresh model in BaseScreen.
- Event-based counting may undercount if event persistence throttling (M20E) drops some progress events. This is acceptable for dashboard display.
