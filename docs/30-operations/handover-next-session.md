# Handover Next Session

## M12 Status: COMPLETE

### Implemented

- **TUI infrastructure** in `src/resemantica/tui/`:
  - `app.py`: `ResemanticaApp` — Textual 8.x app with 7-screen registry, keybindings [1-7] and [q]
  - `palenight.tcss`: Full design system (`#292D3E` background, `#89DDFF` accents)
  - `screens/base.py`: `BaseScreen` — shared shell (header bar, chapter spine, footer), 3s polling loop, tracking repo query helpers
  - `screens/dashboard.py`: run info, phase progress, recent events, quick stats
  - `screens/preprocessing.py`: stage progress bars (Done/Running/Pending)
  - `screens/translation.py`: stage/status header, placeholder block list
  - `screens/warnings.py`: DataTable with severity/event/message
  - `screens/artifacts.py`: Tree widget browsing artifact root
  - `screens/cleanup.py`: Dry Run + Apply buttons (calls orchestration cleanup)
  - `screens/settings.py`: read-only config display

- **Event bus** in `src/resemantica/orchestration/events.py`:
  - `subscribe()`, `unsubscribe()`, `emit_event()` — in-memory bus for live TUI updates

- **3 new CLI commands** in `src/resemantica/cli.py`:
  - `tui`: launches `ResemanticaApp` with optional `--release`, `--run`, `--config`
  - `rebuild-epub`: rebuilds EPUB from unpacked release content via `rebuild_epub()`
  - `translate-range`: translates chapters `--start` to `--end` (inclusive) via `translate_chapter()`

- **`py.typed` marker**: enables mypy inline type checking for the package

### Tests Added

- `tests/cli/test_cli_dispatch.py`: 18 tests — all top-level and sub-command argument parsing
- `tests/tui/test_presenters.py`: 6 tests — event bus (subscribe/unsubscribe/filter), dashboard phase progress, settings config, preprocessing stages

### Verification

```
uv run ruff check src/ tests/        → all checks passed
uv run mypy src/                      → no errors (78 source files)
uv run pytest tests/ -x -q            → 109 passed
```

### Working Tree State

New files:
- `src/resemantica/tui/__init__.py`
- `src/resemantica/tui/app.py`
- `src/resemantica/tui/palenight.tcss`
- `src/resemantica/tui/screens/__init__.py`
- `src/resemantica/tui/screens/base.py`
- `src/resemantica/tui/screens/dashboard.py`
- `src/resemantica/tui/screens/preprocessing.py`
- `src/resemantica/tui/screens/translation.py`
- `src/resemantica/tui/screens/warnings.py`
- `src/resemantica/tui/screens/artifacts.py`
- `src/resemantica/tui/screens/cleanup.py`
- `src/resemantica/tui/screens/settings.py`
- `src/resemantica/py.typed`
- `tests/cli/test_cli_dispatch.py`
- `tests/tui/__init__.py`
- `tests/tui/test_presenters.py`

Modified files:
- `src/resemantica/orchestration/events.py` (added subscribe/unsubscribe)
- `src/resemantica/orchestration/__init__.py` (exports new event bus functions)
- `src/resemantica/cli.py` (added tui, rebuild-epub, translate-range commands)
- `pyproject.toml` (added `textual>=2.0.0` dependency)

### Next Objective

Start **M13** (Observability + Evaluation):

- Task brief: `docs/40-tasks/task-13-observability.md`
- LLD: `docs/20-lld/lld-13-observability.md`
- Depends on: M10 (orchestration context for observability hooks)

No push performed.
