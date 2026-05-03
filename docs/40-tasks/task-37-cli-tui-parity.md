# Task 37: CLI–TUI Feature Parity

## Milestone And Depends On

Milestone: M28

Depends on: M25 (TUI Launch Control), M27 (Cleanup Wizard)

## Goal

Close every remaining gap between CLI and TUI so operators never need to drop to a terminal for any pipeline operation. Every CLI command flag and workflow has a keyboard-driven TUI equivalent.

## Scope

In:

- Replace `#header-container` (1 row) with `#tab-bar` + `#status-bar` (2 rows): collapsible tab bar where inactive screens collapse to `[N]Letter` and the active screen shows full name, with sub-tabs inline.
- Add `short_label: str` and `sub_tabs: tuple[str, ...]` fields to `ScreenInfo` in `navigation.py`; add `format_tab_bar()`.
- Unify all progress indicators to `▓░` block-style completion bars in `base.py`:
  - `_render_scoped_bar` — replace `━┺─` with `▓░` characters
  - `_static_bar` / `_running_bar` — replace line-drawing with `▓░`
  - Header chapter progress: `"Ch 5/20"` → `"▓▓▓░░░░░ Ch 5/20"`
  - Footer block progress: `"8/20 blocks"` → `"▓▓▓░░░░░░░░░░░ 8/20 blk"`
- Dashboard (screen 1):
  - Add numeric `Input` fields for `From Ch` / `To Ch` for chapter-scoped operations
  - Add `f` key to toggle force re-run (skip-cache equivalent)
  - Add `d` key to toggle dry-run mode for production
  - Add recent-runs list with `r` key resume
- Preprocess (screen 3): Simplify to launch+status list with per-subcommand keys:
  `d`=glossary-discover, `t`=glossary-translate, `p`=glossary-promote, `s`=summaries, `i`=idioms, `r`=graph, `b`=packets
- Translation (screen 4): Add `b` key to toggle batched/sequential model ordering
- Settings (screen 8): Add config-path `Input` + `l` key to load alternate `.toml`
- Update `help.py` with new screen and key tables
- Update `palenight.tcss` with tab-bar, status-bar, and bar-character styles

Out:

- Review-then-promote interactive UI (glossary-review / idiom-review generate JSON for external editing — no TUI change needed)
- Pause, cancel, retry, or queue management
- Editing TOML config from the TUI (load alternate file only)
- Multi-run batch scheduler
- Full graphical file browser

## Owned Files Or Modules

- `src/resemantica/tui/navigation.py` — ScreenInfo short_label/sub_tabs, format_tab_bar()
- `src/resemantica/tui/screens/base.py` — tab bar, status bar, progress bar consistency
- `src/resemantica/tui/app.py` — wire tab bar refresh on screen switch
- `src/resemantica/tui/screens/dashboard.py` — chapter scope inputs, force/dry-run/resume keys
- `src/resemantica/tui/screens/preprocessing.py` — per-subcommand key bindings, simplified stage list
- `src/resemantica/tui/screens/translation.py` — batched toggle key
- `src/resemantica/tui/screens/settings.py` — config load input + key
- `src/resemantica/tui/screens/help.py` — new screen/key tables
- `src/resemantica/tui/palenight.tcss` — tab-bar, status-bar, progress bar styles
- `tests/tui/` — updated tests

## Interfaces To Satisfy

- `ScreenInfo` gains `short_label: str` and `sub_tabs: tuple[str, ...]`
- `format_tab_bar(active_screen_id: str) -> str` renders collapsible tab bar markup
- `BaseScreen._render_tab_bar()` called on screen switch + periodic refresh
- `BaseScreen._update_status()` replaces `_update_header()` for the status row
- `_render_scoped_bar` / `_static_bar` / `_running_bar` use `▓░` characters
- `_format_chapter_progress` returns `"▓▓▓░░░░░ Ch N/M"` (10-char bar)
- Footer block progress returns `"▓▓▓░░░░░░░░░░░ N/M blk"` (16-char bar)
- Dashboard: `Input(id="chapter-start")`, `Input(id="chapter-end")`, `Binding("f", ...)`, `Binding("d", ...)`, `Binding("r", ...)`
- Preprocess: `Binding("d", "launch_glossary_discover")`, `Binding("t", "launch_glossary_translate")`, `Binding("p", "launch_glossary_promote")`, `Binding("s", "launch_summaries")`, `Binding("i", "launch_idioms")`, `Binding("r", "launch_graph")`, `Binding("b", "launch_packets")`
- Translation: `Binding("b", "toggle_batched")`
- Settings: `Input(id="config-path-input")`, `Binding("l", "load_config")`

## Tests Or Smoke Checks

- Unit test `ScreenInfo` short_label and sub_tabs fields
- Unit test `format_tab_bar` renders collapsed/active state correctly
- Unit test progress bar helpers produce `▓░` strings of correct width
- Unit test `_format_chapter_progress` returns bar + text format
- Unit test footer block progress uses bar format
- Unit test Dashboard chapter-scope Inputs accept valid ints, reject garbage
- Unit test Preprocess launches correct stage for each key
- Unit test Translation batched toggle toggles state
- Unit test Settings config load rejects non-existent file
- Mounted TUI test: tab bar shows full name on active screen, collapsed on others
- Mounted TUI test: progress bars render consistently across screens
- Run `uv run --with pytest pytest tests/tui -q`
- Run `uv run --with ruff ruff check src tests`
- Run `uv run --with mypy mypy src/resemantica`

## Done Criteria

- Tab bar renders 8 screens with active expansion and inactive collapse
- All progress displays use consistent `▓░` block-style bars
- Chapter scope set on Dashboard propagates to `TuiSession` and launch actions
- Force re-run and dry-run toggles available on Dashboard via `f`/`d`
- Recent runs visible and resumable via `r` on Dashboard
- Preprocess 7-key layout launches correct stage for each key
- Translation `b` key toggles batched/sequential mode
- Settings `l` key loads alternate config file
- Help modal shows 8 screens and all new key bindings
- All tests pass; ruff and mypy clean
- `docs/20-lld/lld-37-cli-tui-parity.md` is implemented and kept in sync
