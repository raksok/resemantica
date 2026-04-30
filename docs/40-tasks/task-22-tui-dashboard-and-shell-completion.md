# Task 22: TUI Dashboard & Shell Completion

## Milestone And Depends On

Milestone: M22

Depends on: M21

## Goal

Replace the remaining placeholder shell widgets (header, footer, pulse bar) and dashboard quick-stats panel with run-derived and event-derived live data, completing the TUI operator console.

## Scope

In:

- Populate header chapter progress (`Ch N/M`) from chapter manifest and run checkpoint.
- Populate header pass indicator (`PASS 1/2/3`, `IDLE`, `PREPROCESS`, `REBUILD`) from run state `stage_name`.
- Replace static pulse bar string with a 30-char ASCII sparkline showing blocks/min from `paragraph_completed` events.
- Color the sparkline `comment` when idle, `cyan` when active, `red` on retry spikes.
- Populate footer block progress, warning count, failure count, and elapsed time from run state and events.
- Replace dashboard `_build_quick_stats()` placeholder with event-derived aggregate counts (glossary, idioms, entities, retries, avg risk).
- Add tests for all replaced widgets.
- Update `lld-22-tui-dashboard-and-shell-completion.md` to stay in sync.

Out:

- Adding new tracking DB tables or columns.
- Visual redesign of the TUI layout or color system.
- Adding new screens or changing screen navigation.
- Block detail overlay (Screen 3 `Enter` drill-down).
- Direct queries to glossary/idiom/graph subsystem repos (use event-based counting only).

## Owned Files Or Modules

- `src/resemantica/tui/screens/base.py`
- `src/resemantica/tui/screens/dashboard.py`
- `tests/tui/`

## Interfaces To Satisfy

- Header `#header-chapter-progress` shows `Ch N/M` derived from `list_extracted_chapters()` and run checkpoint.
- Header `#header-pass` shows pass indicator derived from `state.stage_name`.
- Header `#pulse-bar` shows 30-char ASCII sparkline derived from `paragraph_completed` events.
- Footer `#footer-block-progress` shows `N/M blocks` from run checkpoint.
- Footer `#footer-warnings` shows warning count from events.
- Footer `#footer-failures` shows failure count from events.
- Footer `#footer-elapsed` shows elapsed time from `state.started_at`.
- Dashboard `#dashboard-quick-stats` shows glossary, idiom, entity, retry, and risk aggregates from events.

## Tests Or Smoke Checks

- Unit test header chapter progress rendering with manifest + checkpoint fixture.
- Unit test header pass indicator mapping for each stage name.
- Unit test pulse bar sparkline produces 30 chars from fixture events.
- Unit test pulse bar idle/active/error coloring.
- Unit test footer block count, warnings, failures, elapsed rendering.
- Unit test quick stats renders counts from fixture events.
- Unit test quick stats empty-state when no events exist.
- Run `uv run --with pytest pytest tests/tui -q`.
- Run `uv run --with ruff ruff check src tests`.
- Run `uv run --with mypy mypy src/resemantica`.

## Done Criteria

- Header chapter progress, pass indicator, and pulse bar show run-derived data instead of static strings.
- Footer shows block count, warning/failure counts, and elapsed time instead of only key hints.
- Dashboard quick stats shows event-derived aggregates instead of placeholder text.
- Tests cover all replaced widgets with fixture data.
- `docs/20-lld/lld-22-tui-dashboard-and-shell-completion.md` is implemented and kept in sync.
