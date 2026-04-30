# Task 20: TUI Completion & Reconstruction Smoke Validation

## Milestone And Depends On

Milestone: M20

Depends on: M18, M16, M19

## Goal

Finish the remaining operator-console gaps after Task 18 and prove the reconstruction path against a completed translated run.

## Scope

In:

- Add TUI action controls for launching preprocessing and translation workflows through `TUIAdapter.launch_workflow()`.
- Replace hard-coded chapter spine placeholders with run/release-derived chapter progress where data exists.
- Replace placeholder translation block text with run-derived block or paragraph progress from persisted/live events.
- Keep the TUI functional and conservative; do not redesign the visual style.
- Add tests for launch controls and run-derived progress rendering.
- Document and execute the completed-run reconstruction smoke path where a suitable fixture or local artifact exists.
- Record the manual smoke result, including whether `epubcheck` was available.

Out:

- Changing orchestration state-machine rules.
- Changing translation prompts or pass behavior.
- Adding a full EPUB reader UI.
- Requiring network access or external downloads for smoke validation.

## Owned Files Or Modules

- `src/resemantica/tui/screens/base.py`
- `src/resemantica/tui/screens/preprocessing.py`
- `src/resemantica/tui/screens/translation.py`
- `src/resemantica/tui/adapter.py`
- `tests/tui/`
- `docs/30-operations/` or a task-local smoke result note

## Interfaces To Satisfy

- TUI preprocessing controls call `TUIAdapter.launch_workflow("preprocessing", ...)`.
- TUI translation controls call `TUIAdapter.launch_workflow("translation", ...)`.
- Chapter spine derives chapter counts/status from extracted chapters, run state, checkpoints, or events.
- Translation progress derives block/paragraph status from events and run metadata where available.
- Reconstruction smoke command path remains `resemantica rebuild-epub --release <id> --run-id <id>`.

## Tests Or Smoke Checks

- Unit test preprocessing controls delegate to `TUIAdapter.launch_workflow("preprocessing")`.
- Unit test translation controls delegate to `TUIAdapter.launch_workflow("translation")`.
- Unit test chapter spine uses available extracted chapter count instead of hard-coded 20 chapters.
- Unit test translation screen renders persisted paragraph/block events instead of placeholder copy.
- Run `uv run --with pytest pytest tests/tui -q`.
- Run `uv run --with ruff ruff check src tests`.
- Run `uv run --with mypy mypy src/resemantica`.
- Smoke check `resemantica rebuild-epub --release <id> --run-id <id>` against a completed run if local artifacts exist.
- Run `epubcheck` on the generated EPUB when the executable is available; otherwise record it as skipped.

## Done Criteria

- Preprocessing and translation can be launched from TUI controls without bypassing `TUIAdapter`.
- The chapter spine no longer renders a fixed placeholder set when release/run data is available.
- The translation screen shows real run-derived block or paragraph progress instead of placeholder text.
- Tests cover the new TUI controls and progress renderers.
- Reconstruction smoke validation is documented with command, result, and any skipped external tooling.
- `docs/20-lld/lld-20-tui-completion-and-smoke-validation.md` is implemented and kept in sync.
