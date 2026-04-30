# LLD 22: TUI Dashboard And Shell Completion

## Summary

Task 22 completes the shared shell widgets and dashboard screen that Task 21 left as placeholders. The header bar, footer bar, pulse bar sparkline, and dashboard quick-stats panel all consume run state and persisted events to render live data instead of static or empty content.

## Public Interfaces

Shell (BaseScreen):

- Header chapter progress: `Ch N/M` derived from run checkpoint and chapter manifest
- Header pass indicator: `PASS 1`, `PASS 2`, `PASS 3`, `IDLE`, `PREPROCESS` derived from run state `stage_name`
- Header pulse bar: 30-char Unicode sparkline of persisted paragraph throughput for the active run
- Footer block progress: `N/M blocks` derived from distinct persisted block IDs
- Footer warning count: count of events with `severity = "warning"`
- Footer failure count: count of events with `severity = "error"`
- Footer elapsed time: `H:MM:SS` from `state.started_at` to `state.finished_at` or current UTC time

Dashboard:

- Quick stats panel: aggregate glossary, idiom, entity, retry, and average-risk values from persisted events for the active run

## Data Sources

All data comes from the tracking DB or the chapter manifest. No new repo functions are needed.

| Widget | Query |
|--------|-------|
| Chapter progress `Ch N/M` | `load_run_state()` checkpoint for current chapter index using `chapter_number` first, then max of `completed_chapters` / `pass1_completed` / `pass2_completed` / `pass3_completed`; `list_extracted_chapters()` for total M |
| Pass indicator | `state.stage_name`, `state.checkpoint`, and recent persisted run events mapped to a deterministic pass label |
| Pulse bar sparkline | `load_events(conn, run_id, limit=5000)` filtered to persisted `paragraph_completed` events and bucketed into 30 bins over the run window |
| Block progress `N/M` | Distinct `block_id` values from persisted paragraph/block events for the active run; `paragraph_completed` contributes the completed count |
| Warning count | `load_events()` filtered `severity = "warning"`, counted |
| Failure count | `load_events()` filtered `severity = "error"`, counted |
| Elapsed time | `state.started_at` delta to `state.finished_at` or now |
| Quick stats glossary | Count of `preprocess-glossary.discover.term_found` events |
| Quick stats idioms | Latest `preprocess-idioms.completed` event payload `promoted_count` when present |
| Quick stats entities | Count of `preprocess-graph.entity_extracted` events |
| Quick stats retries | Events with `event_type` containing `retry` |
| Quick stats avg risk | Events whose type contains `risk_detected`, average of numeric `payload.risk_score` |

## Pulse Bar Sparkline

The sparkline is a 30-character Unicode bar showing persisted paragraph throughput for the active run:

- Collect `paragraph_completed` events for the active run from the tracking DB.
- Bucket events into 30 equal time windows covering the active run window from `started_at` to `finished_at` or current UTC time.
- Each bucket maps to one character: `▁▂▃▄▅▆▇█` (8 levels from 0 to max).
- Idle (no active run, inactive run, or no persisted progress yet): flat `▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁` in `comment`.
- Active: sparkline in `cyan`.
- Retry spike (any retry event occurs during the visible run window): color the whole sparkline `red`.
- Update on the shared shell refresh cadence, which remains 3 seconds.

## Stage-To-Pass Mapping

| `stage_name` | Pass Indicator | Color |
|---------------|---------------|-------|
| `preprocess-*`, `packets-build` | `PREPROCESS` | `comment` |
| `translate-chapter` or `translate-range` with no pass hints | `PASS 1` | `cyan` |
| `translate-chapter` or `translate-range` with any stage/checkpoint/event hint containing `pass2` | `PASS 2` | `cyan` |
| `translate-chapter` or `translate-range` with any stage/checkpoint/event hint containing `pass3` | `PASS 3` | `cyan` |
| `epub-rebuild` | `REBUILD` | `green` |
| Missing, inactive, or completed run | `IDLE` | `comment` |

## Quick Stats Rendering

Replace the current placeholder with event-derived counts:

```
  Quick Stats
  Glossary     {glossary_terms} terms
  Idioms       {idiom_promoted} policies
  Entities     {entity_extracted} extracted
  Retries      {retry_total} total
  Avg risk     {avg_risk:.2f or --}
```

All counts come from `load_events()` for the active run, using the actual current emitted event names and payload fields. If there is no active run, or the run has no relevant persisted events yet, the panel shows a clear empty-state message instead of placeholder copy.

## Tests

- Header renders `Ch N/M` from manifest count and checkpoint chapter index.
- Header renders correct pass indicator from each stage name.
- Pulse bar sparkline produces 30 chars from a fixture event list.
- Pulse bar colors: `comment` when idle, `cyan` when active, `red` on retry spike.
- Footer renders block count, warning count, failure count, and elapsed time.
- Footer empty run state falls back to a conservative zero elapsed string.
- Quick stats renders counts from fixture events.
- Quick stats renders empty-state message when no events exist.

Run:

- `uv run --extra dev pytest tests/tui -q`
- `uv run --extra dev ruff check src/resemantica tests`
- `uv run --extra dev mypy src/resemantica`

## Assumptions

- Task 22 does not add new tracking DB tables or columns. All data comes from existing event and run_state tables.
- The pulse bar uses persisted events only (no live subscriber), matching the polling refresh model in BaseScreen.
- Event-based counting may undercount if event persistence throttling (M20E) drops some progress events. This is acceptable for dashboard display.
