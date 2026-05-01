# Task 25: TUI Launch Control & Screen Redesign

## Milestone And Depends On

Milestone: M25

Depends on: M24, M19, M16

## Goal

Upgrade the TUI from a monitor-first interface into a keyboard-driven operator surface with 7 consolidated screens, an EPUB ingestion flow, per-stage launch controls, and full production launch — all operable without a mouse.

This milestone must preserve the current observability and safety work. Launch controls should be explicit, state-aware, disabled when prerequisites are missing, and activated by single-letter key bindings.

## Scope

In:

- Consolidate screen map from 9 to 7 screens:

  | # | Screen | Content |
  |---|--------|---------|
  | 1 | Dashboard | Session context, run state, EPUB Input widget, production/next-stage launch |
  | 2 | Ingestion | Extraction status, chapter manifest, extract launch via `e` |
  | 3 | Preprocess | Per-stage launch: glossary/summaries/idioms/graph/packets via `g`/`s`/`i`/`r`/`b` |
  | 4 | Translation | Block progress, translate/rebuild via `t`/`u` |
  | 5 | Observability | Events stream (top 70%) + warnings DataTable (bottom 30%, pinned) |
  | 6 | Artifact | Artifact tree (top) + unified cleanup section (bottom: scope + Preview/Apply) |
  | 7 | Settings | Read-only config display (unchanged) |

- Add Textual `Input` widget on Dashboard for EPUB path entry — the only text-input field in the TUI, making the TUI standalone-functional.
- Replace all `Button` widgets with single-letter key bindings (`BINDINGS` on each screen) and action methods. No mouse required for any operation.
- Keep all existing screens as source files but stop registering them: `warnings.py`, `cleanup.py`, `reset_preview.py`, `event_log.py`.
- Merge `WarningsScreen` (DataTable) as a pinned 30%-height bottom pane inside `ObservabilityScreen`.
- Merge `CleanupScreen` + `ResetPreviewScreen` into a single unified cleanup section inside `ArtifactScreen` (bottom half, with scope selector and Preview/Apply buttons).
- Merge `ArtifactsScreen` tree into the top half of `ArtifactScreen`.
- Keep `EventLogScreen` observability logic (counters, filters, live/persisted/log events) as the top 70% scrollable pane of `ObservabilityScreen`.
- Add a TUI launch-control model for selected EPUB path, release id, run id, chapter range, current stage, legal next actions, active worker state, latest result, and latest failure.
- Replace fake `EPUB Extract` completion with real extraction status derived from artifacts or persisted events.
- Add per-stage launch controls for all pipeline stages.
- Add full production launch control that delegates to existing orchestration.
- Use Textual `@work(thread=True)` for all background launch work.
- Enforce cross-screen single-worker guard via app-level `active_action` state.
- Centralize worker launch into one `BaseScreen.start_worker(action_key, callable)` helper.
- Add a `TuiSession` dataclass on `ResemanticaApp` as the single source of truth for `input_path`, `chapter_start`, `chapter_end`.
- Define a `StageKey` type alias (`Literal[...]`) for stage keys.
- Route `TUIAdapter.extract_epub()` passes `run_id=self.run_id` to `extract_epub()` so extraction events appear under the pipeline run_id.
- Presenter derives stage enablement by calling `orchestration.models.legal_transition()` directly.
- Extract stale-detection logic into shared `is_stale()` helper.
- Add tests for launch-control presenter logic, adapter delegation, extraction prerequisites, stage enablement, mounted TUI controls, and failure rendering.

Out:

- Pause, cancel, resume, retry, or queue management.
- Editing TOML config from the TUI.
- Full graphical file browser.
- Multi-run batch scheduler.
- Destructive reset/apply redesign beyond the unified cleanup section.
- Replacing CLI behavior.

## Owned Files Or Modules

- `src/resemantica/tui/adapter.py` — already extended with extract_epub(), launch_stage(), launch_production()
- `src/resemantica/tui/launch_control.py` — already created with data models + build_snapshot()
- `src/resemantica/tui/app.py` — update SCREENS dict, BINDINGS, imports
- `src/resemantica/tui/navigation.py` — rewrite SCREEN_INFOS to 7 entries
- `src/resemantica/tui/screens/dashboard.py` — add Input widget + key bindings
- `src/resemantica/tui/screens/ingestion.py` — NEW: extraction status + chapter manifest
- `src/resemantica/tui/screens/preprocessing.py` — buttons → BINDINGS for g/s/i/r/b
- `src/resemantica/tui/screens/translation.py` — buttons → BINDINGS for t/u
- `src/resemantica/tui/screens/observability.py` — NEW: combine event log (top) + warnings (bottom pinned)
- `src/resemantica/tui/screens/artifact.py` — NEW: combine artifact tree (top) + cleanup section (bottom)
- `src/resemantica/tui/screens/settings.py` — update screen info ref only
- `src/resemantica/tui/screens/help.py` — update screen list + key table
- `src/resemantica/tui/screens/__init__.py` — export new screens, remove old
- `src/resemantica/tui/palenight.tcss` — add new content IDs, split-pane layout rules
- `src/resemantica/tui/screens/base.py` — already has start_worker, build_snapshot, is_stale (keep as-is)
- `tests/tui/` — new tests for combined screens

## Interfaces To Satisfy

- The TUI exposes 7 screens navigable via keys `1`–`7`.
- Every launch action is invocable via a single-letter key — no mouse required.
- The operator can specify:
  - EPUB input path via Textual Input widget on Dashboard
  - release id / run id via CLI constructor args (read-only in TUI)
  - chapter range via TuiSession fields when applicable
- Each screen's BINDINGS are screen-local (not global), preventing key conflicts between screens that share letters.
- Launch controls must be disabled when:
  - no EPUB path is selected for extraction
  - no release/run is selected for orchestration stages
  - extraction artifacts or chapter manifest are missing for preprocessing
  - stage transition would violate `legal_transition`
  - another TUI-launched worker is active (guard is app-level, not per-screen)
- Active launch state must show: action name, spinner indicator, latest failure if present.
- All launch actions delegate to existing domain APIs.

## Tests Or Smoke Checks

- Unit test launch-control state derives legal actions for no file, selected file, extracted release, running stage, completed stage, stale state, and failed state.
- Unit test stage action ordering respects `legal_transition`.
- Unit test extraction action requires a readable `.epub` path.
- Unit test adapter delegates extraction to `extract_epub` and stage launch to `OrchestrationRunner`.
- Unit test extraction uses the same `run_id` as the pipeline.
- Unit test fake `EPUB Extract DONE` is gone when extraction artifacts are missing.
- Mounted TUI test Dashboard renders Input widget + disabled launch controls without release/run/file.
- Mounted TUI test Input validation: rejects non-existent path, rejects non-.epub, accepts valid path.
- Mounted TUI test setting an EPUB path enables extraction on screens 1 and 2.
- Mounted TUI test pressing launch key on one screen then another is blocked by app-level active_action guard.
- Mounted TUI test active worker key is repeatable (pressing same key twice shows warning).
- Mounted TUI test stage failure renders latest failure without crashing.
- Mounted TUI test Observability screen shows events in top pane + warnings bottom pane.
- Mounted TUI test Observability bottom warnings pane scrolls independently from top events pane.
- Mounted TUI test Artifact screen renders tree + cleanup section without crashing.
- Mounted TUI test cleanup Preview/Apply work on Artifact screen.
- Mounted TUI test Settings screen remains read-only and has no launch controls.
- Run `uv run --with pytest pytest tests/tui tests/orchestration -q`.
- Run `uv run --with ruff ruff check src/resemantica/tui tests/tui`.
- Run `uv run --with mypy mypy src/resemantica/tui --ignore-missing-imports`.

## Done Criteria

- Operators can start at Dashboard, enter EPUB path, switch to Ingestion, extract, proceed through preprocess/translation/rebuild using only single-letter keys.
- 7-screen navigation works: `1`–`7` switch screens, `?` opens help, `q` quits.
- Every launchable action has a single-letter key visible in screen key hints and help modal.
- TUI works entirely without mouse: keyboard-only operation for all primary actions.
- EPUB path entry via Input widget on Dashboard validates (exists, `.epub`, readable) and stores in TuiSession.
- Launch workers use Textual `@work(thread=True)` — no raw `threading.Thread` in screen code.
- Cross-screen worker guard prevents overlapping launches from different screens.
- Session state is shared between screens via TuiSession on the app.
- Presenter delegates stage ordering to `legal_transition()`.
- TUI launch controls are state-aware, disabled safely, and do not block the UI thread.
- Every launched action is observable through Observability screen and tracking DB.
- Missing prerequisites and failed stages render clear explanations.
- Existing read-only observability behavior (filters, verbosity, counters) remains intact.
- Tests cover launch-control state, adapter delegation, mounted control states, combined screen rendering, and failure display.
- `docs/20-lld/lld-25-tui-launch-control.md` is implemented and kept in sync.
