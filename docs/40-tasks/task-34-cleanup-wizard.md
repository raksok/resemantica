# Task 34: Cleanup Wizard TUI Screen

## Milestone And Depends On

Milestone: M27

Depends on: M25 (TUI Launch Control), M11 (Cleanup Workflow)

## Goal

Replace the current combined artifact-tree + cleanup-preview bottom-pane on Screen 6 with a dedicated, step-by-step **Cleanup Wizard** as Screen 7. The wizard guides the user through scope selection, preview, confirmation, and result review — making cleanup safe, discoverable, and unambiguous.

Add a `factory` scope to purge all releases and databases across the entire artifact root.

## Scope

In:

- New `CleanupWizardScreen` at Screen 7 (8 screens total).
- Four-step wizard: Scope → Preview → Confirm → Result.
- Scope selection via `s` key cycling through `run` → `translation` → `preprocess` → `cache` → `all` → `factory`.
- Preview groups deletable artifacts by category (run dir, translation output, preprocess artifacts, etc.) instead of raw path dump.
- Estimated size and item counts shown at each step.
- Guard: Apply only enabled after preview has been run.
- Guard: Confirm step must be reached and shown before Apply activates.
- Artifact screen simplified to tree-only (cleanup section removed).
- Help modal updated with 8-screen list and wizard keys.
- Navigation and screen switching keys `1`–`8` updated.
- **New factory scope** in `cleanup.py`: purges all releases, all run directories, and the global database. No run_id needed.
- **Factory scope** in wizard: extra-strong warning on confirm step, works without release/run context.
- Tests for wizard state machine, scope cycling, preview rendering, apply guard, navigation, and factory scope.

Out:

- Automatic or scheduled cleanup.
- Multi-scope batch cleanup.
- Editing scope behavior beyond the 6 existing scopes.

## Owned Files Or Modules

- `src/resemantica/tui/screens/cleanup_wizard.py` — NEW
- `src/resemantica/tui/screens/artifact.py` — simplify to tree-only
- `src/resemantica/tui/navigation.py` — 8 entries
- `src/resemantica/tui/screens/__init__.py` — add wizard export
- `src/resemantica/tui/app.py` — register wizard screen
- `src/resemantica/tui/screens/help.py` — 8 screens + wizard keys
- `src/resemantica/tui/palenight.tcss` — wizard styles
- `src/resemantica/orchestration/cleanup.py` — add factory scope
- `tests/tui/test_cleanup_wizard.py` — NEW
- `tests/orchestration/test_orchestration.py` — factory scope tests

## Interfaces To Satisfy

- Screen 7 is the Cleanup Wizard, navigable via `7` key.
- Screen 6 (Artifact) is tree-only — no cleanup section or bindings.
- Wizard shows current step (1–4) and total steps.
- `s` cycles through 6 scopes, `p` previews/advances, `b` goes back, `a` applies (only on confirm step).
- `Esc` on wizard switches to Artifact screen.
- Scope cycling immediately calls `plan_cleanup(dry_run=True)` and updates preview.
- Preview groups artifacts by category, shows preserved items, estimated size, and SQLite row count.
- Confirm step shows summary and enables `a` key.
- Factory scope confirm shows extra-strong warning: "This will delete ALL releases and ALL databases."
- Factory scope does not require `release_id` or `run_id` to plan or apply.
- Result step shows post-apply report (files, dirs, SQLite rows, errors).
- `plan_cleanup(scope="factory")` ignores release_id and run_id, collects all releases + global DB.
- `apply_cleanup(scope="factory")` deletes all release directories and global DB file.

## Tests Or Smoke Checks

- Unit test state machine: scope step → preview → confirm → result.
- Unit test scope cycling through all 6 values.
- Unit test preview calls `plan_cleanup` and renders grouped output.
- Unit test apply without preview shows error.
- Unit test apply on non-confirm step is no-op.
- Unit test artifact screen has no cleanup sections.
- Unit test factory scope plan collects releases dir + global DB.
- Unit test factory scope apply deletes releases dir + global DB.
- Mounted TUI test: pressing `7` opens wizard, shows step 1.
- Mounted TUI test: scope cycling updates display through factory.
- Run `uv run --with pytest pytest tests/tui tests/orchestration -q`.
- Run `uv run --with ruff ruff check src/resemantica/tui src/resemantica/orchestration tests`.
- Run `uv run --with mypy mypy src/resemantica/tui --ignore-missing-imports`.

## Done Criteria

- Cleanup wizard is a dedicated screen (7) with 4-step flow.
- Artifact screen (6) is clean - tree browsing only.
- Scope cycling with `s` key updates preview in real time through all 6 scopes including factory.
- Preview groups artifacts by logical category.
- Apply is guarded: only reachable after preview on confirm step.
- Factory scope shows prominent warning on confirm.
- Help modal shows 8 screens and wizard key bindings.
- Navigation keys `1`–`8` work correctly.
- Factory scope plan and apply work without release/run context.
- All existing tests pass.
