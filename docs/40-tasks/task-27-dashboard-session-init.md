# Task 27: Dashboard Session Initialisation

## Milestone And Depends On

Milestone: M27

Depends on: M26 (global tracking / observability pipeline)

## Goal

Replace the Dashboard's free-form `Input` for EPUB path entry with two curated action buttons — **New File** and **Resume Run** — accessed via arrow-key navigation and Enter. Each action opens a modal dialog that collects the required session identifiers (file path for new, release ID, run ID). This eliminates the ambiguous state where a user has typed a path but has no release/run scope, and prevents accidental extraction into the wrong release.

## Scope

### In

- Replace `Input(placeholder="/path/to/book.epub ...", id="epub-path-input")` in `DashboardScreen._content_widgets()` with a `ListView` containing two `ListItem` widgets: "New File" and "Resume Run".
- Remove `on_input_submitted()`, `action_focus_input()`, `action_blur_input()` from `DashboardScreen`.
- Remove `e` and `escape` bindings from `DashboardScreen.BINDINGS`.
- Add `on_list_view_selected()` handler that dispatches to the appropriate dialog.
- Create `src/resemantica/tui/screens/run_dialog.py` with two `ModalScreen` subclasses.
- `NewFileDialog`: three `Input` fields (path, release, run), Submit/Cancel buttons. Validates path (exists, .epub, readable) and non-empty release/run. Returns `(Path, str, str) | None`.
- `ResumeRunDialog`: two `Input` fields (release, run), Submit/Cancel buttons. Validates non-empty fields. Returns `(str, str) | None`. Clears `session.input_path` on submit.
- Add `set_ids(release_id, run_id)` method to `ResemanticaApp`.
- Wire the dialog callback to set `app.session.input_path` (for New File), call `app.set_ids()`, and refresh the Dashboard.
- Update `_refresh_dashboard()` session-info section to render correctly when only IDs are set (no path).
- Update key hints and help text in `_refresh_dashboard()`.
- Update `palenight.tcss`: replace `#epub-path-input` styles with `#dashboard-action-list` styles; add dialog styles for `#new-file-dialog` and `#resume-run-dialog` (following the `#help-dialog` pattern).
- Remove or update `test_observability.py`'s reliance on setting `active_action` via old path — the live event test should still work since it uses its own `app.active_action = "test-action"` setup.
- Update or replace `test_tui_header_and_footer_show_current_screen_location` if it depends on the old input-flow key bindings.
- Verify: `ruff check`, `mypy`, full `pytest` suite green.

### Out

- Editing release/run after initial set (no "change IDs" action). User can re-use New File or Resume Run to overwrite.
- Persisting session state across TUI restarts (no last-used-IDs file).
- Multiple file history or recent-session list.
- Keyboard shortcuts for dialog inputs beyond Tab/Shift+Tab/Enter.

## Implementation Plan

```
1. Create run_dialog.py         → NewFileDialog, ResumeRunDialog
2. Modify dashboard.py          → replace Input with ListView, add handler, remove old methods
3. Modify app.py                → add set_ids() method
4. Modify palenight.tcss        → update/replace styles
5. Update tests                 → adjust any tests that reference old Input/event pattern
6. Verify                      → ruff, mypy, full pytest
```

## Key Decisions

- **Arrow-key navigation** comes for free with `ListView`; no custom focus management needed.
- **Dialogs push on top** rather than replacing screen content; this matches the existing `HelpScreen` modal pattern and avoids dashboard-layout complexity.
- **Resume Run clears the file path** to prevent accidental extractions into a resumed release. The user can always pick "New File" to re-set the path.
- **CLI flags (`--release`, `--run`) remain optional.** If provided, IDs are pre-set and no dialog prompt appears on file load. The dashboard session info reflects the pre-set values.
- **Path validation happens in the dialog**, not on the dashboard. This keeps the dashboard's render code simple and the validation logic colocated with the input fields.

## Verification

| Check | Command |
|-------|---------|
| Lint | `uv run --with ruff ruff check src/resemantica/tui/` |
| Types | `uv run --with mypy mypy src/resemantica/tui/` |
| Tests | `uv run --with pytest pytest -v` |
