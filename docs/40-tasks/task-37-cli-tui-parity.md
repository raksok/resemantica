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
- Unify all progress indicators to `▓░` block-style completion bars in `base.py`.
- Dashboard (screen 1):
  - **Key hints section** showing `[n] New File  [r] Resume Run  [c] Scope  [f] Force  [d] Dry-Run  [p] Production`
  - `n` key pushes `NewFileDialog` (set EPUB path, release ID, run ID, chapter bounds)
  - `r` key pushes `ResumeRunDialog` (set release/run IDs, chapter bounds)
  - `c` key pushes new `ChapterScopeDialog` (set From/To Ch)
  - `f` key toggles force re-run, `d` toggles dry-run
  - Chapter-scope Inputs moved to dedicated modal dialog instead of inline fields
- Preprocess (screen 3): Simplify to launch+status list with per-subcommand keys:
  `d`=glossary-discover, `t`=glossary-translate, `p`=glossary-promote, `s`=summaries, `i`=idioms, `r`=graph, `b`=packets
- Translation (screen 4): Add `b` key to toggle batched/sequential model ordering
- Settings (screen 8): Add config-path `Input` + `l` key to load alternate `.toml`
- Update `help.py` with new screen and key tables
- Update `palenight.tcss` with tab-bar, status-bar, key-hints, and dashboard content styles

Out:

- Review-then-promote interactive UI (glossary-review / idiom-review generate JSON for external editing — no TUI change needed)
- Pause, cancel, retry, or queue management
- Editing TOML config from the TUI (load alternate file only)
- Multi-run batch scheduler
- Full graphical file browser

## Owned Files Or Modules

- `src/resemantica/tui/navigation.py`
- `src/resemantica/tui/screens/base.py`
- `src/resemantica/tui/screens/run_dialog.py` — NEW `ChapterScopeDialog` + `ChapterScopeResult`
- `src/resemantica/tui/app.py`
- `src/resemantica/tui/screens/dashboard.py` — key hints, dialog actions, no inline scope inputs
- `src/resemantica/tui/screens/preprocessing.py`
- `src/resemantica/tui/screens/translation.py`
- `src/resemantica/tui/screens/settings.py`
- `src/resemantica/tui/screens/help.py`
- `src/resemantica/tui/palenight.tcss`
- `tests/tui/`

## Interfaces To Satisfy

- `ScreenInfo` gains `short_label: str` and `sub_tabs: tuple[str, ...]`
- `format_tab_bar(active_screen_id: str) -> str` renders collapsible tab bar markup
- `BaseScreen._render_tab_bar()` called on screen switch + periodic refresh
- `BaseScreen._update_status()` replaces `_update_header()` for the status row
- `_render_scoped_bar` / `_static_bar` / `_running_bar` use `▓░` characters
- `_format_chapter_progress` returns `"▓▓▓░░░░░ Ch N/M"` (10-char bar)
- Footer block progress returns `"▓▓▓░░░░░░░░░░░ N/M blk"` (16-char bar)
- `ChapterScopeResult` dataclass with `chapter_start` / `chapter_end`
- `ChapterScopeDialog(ModalScreen[ChapterScopeResult | None])` with two Input fields + submit/cancel
- Dashboard: `Binding("n", "new_file")`, `Binding("r", "resume_run")`, `Binding("c", "set_scope")`
- Dashboard: key hints Static showing all 6 action keys
- Preprocess: 7-key bindings
- Translation: `Binding("b", "toggle_batched")`
- Settings: `Input(id="config-path-input")`, `Binding("l", "load_config")`

## Tests Or Smoke Checks

- Unit test `ChapterScopeResult` dataclass fields
- Unit test `ChapterScopeDialog` submit: valid ints → returns `ChapterScopeResult`, empty → None chapters, garbage → error notification
- Unit test progress bar helpers produce `▓░` strings
- Unit test Preprocess launches correct stage for each key
- Unit test Translation batched toggle toggles state
- Unit test Settings config load rejects non-existent file
- Run `uv run --with pytest pytest tests/tui -q`
- Run `uv run --with ruff ruff check src tests`
- Run `uv run --with mypy mypy src/resemantica`

## Done Criteria

- Tab bar renders 8 screens with active expansion and inactive collapse
- All progress displays use consistent `▓░` block-style bars
- Dashboard shows key hints for all 6 actions: [n] [r] [c] [f] [d] [p]
- `n` pushes `NewFileDialog`, result populates session + release/run IDs
- `r` pushes `ResumeRunDialog`, result populates release/run IDs + chapter bounds
- `c` pushes `ChapterScopeDialog`, result updates `session.chapter_start` / `chapter_end`
- `f` toggles force re-run, `d` toggles dry-run mode
- Preprocess 7-key layout launches correct stage for each key
- Translation `b` key toggles batched/sequential mode
- Settings `l` key loads alternate config file
- Help modal shows 8 screens and all new key bindings
- All tests pass; ruff and mypy clean
- `docs/20-lld/lld-37-cli-tui-parity.md` is implemented and kept in sync
