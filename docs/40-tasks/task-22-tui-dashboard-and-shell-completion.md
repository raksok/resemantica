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
- Keep shared shell widgets stable across refreshes; refresh logic must update existing mounted widgets instead of removing and remounting duplicate-ID children on the polling cadence.
- Add at least one mounted-screen smoke test that exercises `ResemanticaApp` / `DashboardScreen` initial load and first shared-shell refresh without `DuplicateIds` or other lifecycle errors.
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
- `src/resemantica/tui/app.py`
- `tests/tui/`

## Interfaces To Satisfy

- Header `#header-chapter-progress` shows `Ch N/M` derived from `list_extracted_chapters()` and run checkpoint.
- Header `#header-pass` shows pass indicator derived from `state.stage_name`.
- Header `#pulse-bar` shows 30-char ASCII sparkline derived from `paragraph_completed` events.
- Shared shell refreshes are idempotent and do not recreate fixed-ID children such as `#spine-title`.
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
- Mounted-app smoke test launches the dashboard screen through Textual lifecycle and proves the first shell refresh does not raise `DuplicateIds`.
- Run `uv run --with pytest pytest tests/tui -q`.
- Run `uv run --with ruff ruff check src tests`.
- Run `uv run --with mypy mypy src/resemantica`.

## Done Criteria

- Header chapter progress, pass indicator, and pulse bar show run-derived data instead of static strings.
- Footer shows block count, warning/failure counts, and elapsed time instead of only key hints.
- Dashboard quick stats shows event-derived aggregates instead of placeholder text.
- Shared shell refresh is stable under initial mount and periodic polling.
- Tests cover all replaced widgets with fixture data and at least one real mounted-screen lifecycle path.
- `docs/20-lld/lld-22-tui-dashboard-and-shell-completion.md` is implemented and kept in sync.

## Deep-Dive Notes

- The current TUI boot failure came from `_update_spine()` removing children and immediately remounting a new `Static(id="spine-title")` on every refresh. Task 22 must treat fixed shell widgets as persistent nodes, not ephemeral render output.
- Existing presenter-heavy tests passed while the real app still crashed on startup. This task is not complete unless a mounted Textual lifecycle test closes that gap.
- Additional TUI drift found outside this slice: warnings screen event scoping, config-path consistency in non-shell screens, and dead CSS selectors. Those are follow-on items unless required to unblock the mounted shell fix.
