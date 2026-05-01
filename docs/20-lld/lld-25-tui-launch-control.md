# LLD 25: TUI Launch Control & Screen Redesign

## Summary

Task 25 turns the TUI into a keyboard-driven operator surface: 7 consolidated screens, a standalone EPUB ingestion flow, per-stage launch controls via single-letter key bindings, and full production launch. The existing Material Palenight theme is preserved. All Button widgets are replaced with BINDINGS-based action methods — the TUI is fully operable without a mouse.

## Screen Map

| # | Screen | Screen ID | Class | Label | Purpose |
|---|--------|-----------|-------|-------|---------|
| 1 | Dashboard | `dashboard` | `DashboardScreen` | `Dashboard` | Session context, Input widget, production/next launch |
| 2 | Ingestion | `ingestion` | `IngestionScreen` | `Ingestion` | Extraction status, chapter manifest |
| 3 | Preprocess | `preprocessing` | `PreprocessingScreen` | `Prep` | Per-stage launch g/s/i/r/b |
| 4 | Translation | `translation` | `TranslationScreen` | `Translate` | Block progress, translate/rebuild |
| 5 | Observability | `observability` | `ObservabilityScreen` | `Observe` | Events (top 70%) + warnings (bottom 30% pinned) |
| 6 | Artifact | `artifact` | `ArtifactScreen` | `Artifact` | Tree (top) + cleanup (bottom) |
| 7 | Settings | `settings` | `SettingsScreen` | `Settings` | Read-only config |

## Navigation Changes

### `navigation.py`

Replace `SCREEN_INFOS` with 7 entries:

```python
SCREEN_INFOS: tuple[ScreenInfo, ...] = (
    ScreenInfo(1, "dashboard", "DashboardScreen", "Dashboard", "Dashboard", "Run overview"),
    ScreenInfo(2, "ingestion", "IngestionScreen", "Ingestion", "Ingestion", "EPUB path and extraction"),
    ScreenInfo(3, "preprocessing", "PreprocessingScreen", "Prep", "Preprocessing", "Prepare chapters"),
    ScreenInfo(4, "translation", "TranslationScreen", "Translate", "Translation", "Translation progress"),
    ScreenInfo(5, "observability", "ObservabilityScreen", "Observe", "Observability", "Run signals and logs"),
    ScreenInfo(6, "artifact", "ArtifactScreen", "Artifact", "Artifact", "Output files and cleanup"),
    ScreenInfo(7, "settings", "SettingsScreen", "Settings", "Settings", "Active config"),
)
```

This automatically generates `1`–`7` bindings in `app.py`.

### `screens/__init__.py`

Replace exports:

```python
from resemantica.tui.screens.dashboard import DashboardScreen
from resemantica.tui.screens.ingestion import IngestionScreen
from resemantica.tui.screens.preprocessing import PreprocessingScreen
from resemantica.tui.screens.translation import TranslationScreen
from resemantica.tui.screens.observability import ObservabilityScreen
from resemantica.tui.screens.artifact import ArtifactScreen
from resemantica.tui.screens.settings import SettingsScreen
from resemantica.tui.screens.help import HelpScreen
```

### `app.py`

```python
SCREENS = {
    "dashboard": DashboardScreen,
    "ingestion": IngestionScreen,
    "preprocessing": PreprocessingScreen,
    "translation": TranslationScreen,
    "observability": ObservabilityScreen,
    "artifact": ArtifactScreen,
    "settings": SettingsScreen,
    "help": HelpScreen,
}
```

Keep existing imports (`from resemantica.tui.launch_control import TuiSession`, `from resemantica.tui.navigation import SCREEN_INFOS, screen_info_for_class_name`). Remove imports for `WarningsScreen`, `CleanupScreen`, `EventLogScreen`, `ResetPreviewScreen`, `ArtifactsScreen`.

## Key Binding Architecture

### Global keys (app.py BINDINGS, priority=True)

| Key | Action |
|-----|--------|
| `1`–`7` | `switch_screen(...)` |
| `?` | `show_help` |
| `q` | `quit` |

### Screen-local keys (each screen's BINDINGS)

Screens declare their own bindings. Textual applies screen bindings when that screen is active. This prevents conflicts between screens that both use the same letter (e.g. `e` on Dashboard and `e` on Ingestion — only the active screen's binding fires).

### ObservabilityScreen BINDINGS (carried over from EventLogScreen)

```python
BINDINGS = [
    Binding("v", "cycle_verbosity", "Verbose"),
    Binding("s", "cycle_source", "Source"),
    Binding("e", "cycle_severity", "Severity"),
    Binding("f", "cycle_stage_filter", "Stage"),
    Binding("c", "cycle_chapter_filter", "Chapter"),
    Binding("r", "refresh_observability", "Refresh"),
]
```

Note: screen-local `e` for severity cycling on screen 5 does NOT conflict with global `e` on screen 1 because they're on different screens.

### Full key assignment by screen

| Screen | Keys | Actions |
|--------|------|---------|
| 1 Dashboard | `e` = set EPUB path (focus Input), `p` = production, `n` = next stage | 3 keys |
| 2 Ingestion | `e` = extract EPUB | 1 key |
| 3 Preprocess | `g` = glossary, `s` = summaries, `i` = idioms, `r` = graph, `b` = packets | 5 keys |
| 4 Translation | `t` = translate, `u` = rebuild | 2 keys |
| 5 Observability | `v` = verbosity, `s` = source, `e` = severity, `f` = stage, `c` = chapter, `r` = refresh | 6 keys |
| 6 Artifact | `y` = dry-run preview, `a` = apply cleanup | 2 keys |
| 7 Settings | (none — read-only) | 0 keys |

## Per-Screen Specifications

### Screen 1: DashboardScreen

**Purpose**: Command center — session context, EPUB path entry, production/next-stage launch.

**Widget layout** (`_content_widgets`):
```python
with Container(id="dashboard-content"):
    yield Static("Dashboard", classes="app-title")
    yield Input(placeholder="/path/to/book.epub", id="epub-path-input")
    yield Static("", id="dashboard-session-info")
    yield Static("", id="dashboard-stage-list")
    yield Static("", id="dashboard-active-worker")
    yield Static("", id="dashboard-latest-failure")
```

**BINDINGS**:
```python
BINDINGS = [
    Binding("e", "focus_input", "Set EPUB Path"),
    Binding("p", "launch_production", "Production"),
    Binding("n", "launch_next", "Next Stage"),
]
```

**Behavior**:
- `on_mount`: subscribe to `Input.Submitted` on `#epub-path-input`.
- `on_input_submitted`: validate path (exists, file, `.epub` suffix), store in `session.input_path`. Show error in a `notify()` if invalid. Show success in a Static.
- `_refresh_all` + dashboard refresh: snapshots via `_build_snapshot()`, renders session info, stage list, active worker, latest failure.
- `action_launch_production`: calls `start_worker("production", lambda: adapter.launch_production())`.
- `action_launch_next`: calls `next_available_stage(snapshot)` and launches that stage.
- `action_focus_input`: focuses the Input widget for typing.

**Validation rules on Input.Submitted**:
1. Expand `~` and resolve relative from CWD.
2. Check `path.exists()` — notify error if not.
3. Check `path.is_file()` — notify error if directory.
4. Check `path.suffix == ".epub"` — notify error if wrong extension.
5. Check `os.access(path, os.R_OK)` — notify error if not readable.
6. On success: `self.app.session.input_path = resolved`.
7. Clear Input value, show success text.

### Screen 2: IngestionScreen

**Purpose**: Display extraction status and chapter manifest. Launch extraction.

**Widget layout**:
```python
with Container(id="ingestion-content"):
    yield Static("Ingestion / Extraction", classes="app-title")
    yield Static("", id="ingestion-path")
    yield Static("", id="ingestion-status")
    yield Static("", id="ingestion-chapter-list")
```

**BINDINGS**:
```python
BINDINGS = [
    Binding("e", "launch_extract", "Extract"),
]
```

**Behavior**:
- Reads `session.input_path` from app and displays it.
- Shows extraction status from `build_snapshot()` (missing/ready/running/done/failed).
- Shows chapter manifest list (chapter numbers and titles) when extraction is done.
- `action_launch_extract`: if `session.input_path` is set, calls `start_worker("epub-extract", lambda: adapter.extract_epub(resolved))`.
- If no path is set, show a hint: "Set EPUB path on Dashboard first."
- Refresh every 2s to pick up extraction completion.

**Chapter list format**:
```
Extracted Chapters (12):
  Ch 1  titlepage
  Ch 2  chapter-01
  Ch 3  chapter-02
  ...
```

### Screen 3: PreprocessingScreen

**Purpose**: Per-stage launch for preprocess-glossary through packets-build.

**Widget layout** (unchanged from current, remove Button widgets):
```python
with Container(id="preprocessing-content"):
    yield Static("Preprocessing Stages", classes="app-title")
    yield Static("", id="preprocessing-stage-list")
    yield Static("", id="preprocessing-status")
```

**BINDINGS**:
```python
BINDINGS = [
    Binding("g", "launch_glossary", "Glossary"),
    Binding("s", "launch_summaries", "Summaries"),
    Binding("i", "launch_idioms", "Idioms"),
    Binding("r", "launch_graph", "Graph"),
    Binding("b", "launch_packets", "Packets"),
]
```

**Action methods** — each calls `start_worker(...)` with the corresponding stage key:
```python
def action_launch_glossary(self) -> None:
    self._launch_stage("preprocess-glossary")
def action_launch_summaries(self) -> None:
    self._launch_stage("preprocess-summaries")
# ... etc
```

**`_launch_stage(stage_key)`** — same logic as current implementation: get adapter, call `start_worker`.

**Stage rendering** — use `_build_stage_progress(state)` which now delegates to `build_snapshot()` for real status. The stage list shows all 6 prepro stages with status bars. The status line shows active worker and latest failure.

### Screen 4: TranslationScreen

**Purpose**: Translation block progress + launch translation/rebuild.

**Widget layout** (unchanged from current, remove Button widgets):
```python
with Container(id="translation-content"):
    yield Static("Translation Progress", classes="app-title")
    yield Static("", id="translation-header")
    yield Static("", id="translation-block-list")
    yield Static("", id="translation-status")
```

**BINDINGS**:
```python
BINDINGS = [
    Binding("t", "launch_translate", "Translate"),
    Binding("u", "launch_rebuild", "Rebuild"),
]
```

**Action methods**:
```python
def action_launch_translate(self) -> None:
    adapter = self._make_adapter()
    if adapter is None:
        return
    kwargs = {}
    if self.app.session.chapter_start is not None:
        kwargs["chapter_start"] = self.app.session.chapter_start
    if self.app.session.chapter_end is not None:
        kwargs["chapter_end"] = self.app.session.chapter_end
    self.start_worker("translate-range", lambda: adapter.launch_stage("translate-range", **kwargs))

def action_launch_rebuild(self) -> None:
    self.start_worker("epub-rebuild", lambda: adapter.launch_stage("epub-rebuild"))
```

**Status line** shows active worker and latest failure from `build_snapshot()`.

### Screen 5: ObservabilityScreen

**Purpose**: Monitor pipeline execution. Combines EventLogScreen (top 70%, scrollable) with WarningsScreen DataTable (bottom 30%, pinned).

**This is the most complex new screen. Implementation detail below.**

**Widget layout**:
```python
def _content_widgets(self) -> ComposeResult:
    with Container(id="observability-content"):
        yield VerticalScroll(id="observability-top", classes="observability-pane"):
            yield Static("Observability", classes="app-title")
            yield Static("", id="observability-counters")
            yield Static("", id="observability-latest-failure")
            yield Static("", id="observability-filters")
            yield Static("", id="observability-live")
            yield Static("", id="observability-persisted")
            yield Static("", id="observability-logs")
        yield Static("", id="observability-divider")
        with Vertical(id="observability-bottom", classes="observability-pane"):
            yield Static("Warnings & Failures", id="observability-warnings-header", classes="section-title")
            yield DataTable(id="observability-warnings-table")
```

**Layout in TCSS**:
```css
#observability-content {
    layout: vertical;
    height: 1fr;
}

#observability-top {
    height: 70%;
    overflow-y: auto;
    border-bottom: solid #34324A;
}

#observability-divider {
    height: 1;
    background: #34324A;
}

#observability-bottom {
    height: 30%;
    overflow-y: auto;
}

#observability-warnings-table {
    height: 1fr;
}
```

**BINDINGS** — same as current EventLogScreen:
```python
BINDINGS = [
    Binding("v", "cycle_verbosity", "Verbose"),
    Binding("s", "cycle_source", "Source"),
    Binding("e", "cycle_severity", "Severity"),
    Binding("f", "cycle_stage_filter", "Stage"),
    Binding("c", "cycle_chapter_filter", "Chapter"),
    Binding("r", "refresh_observability", "Refresh"),
]
```

**Behavior** — port everything from EventLogScreen (240 lines) into the top pane logic:
- `on_mount`: set up empty state, subscribe to EventBus `"*"`, call super.
- `on_unmount`: unsubscribe.
- `_refresh_all`: call super, then `_refresh_observability`.
- `_on_event`: filter by release_id/run_id, buffer events (max 100), schedule refresh via `call_from_thread`.
- `_refresh_observability`: load persisted events, log records, build snapshot, render top content + bottom warnings table.
- `_render_observability`: render counters, latest failure, filters, live events, persisted events, logs (same as current EventLogScreen).
- `_render_warnings`: render DataTable from persisted events (same as current WarningsScreen, but using the same `persisted_events` already loaded).
- All filter actions (`action_cycle_verbosity`, etc.) — same as current EventLogScreen.

**Bottom warnings table**:
- Uses the same `persisted_events` loaded by `_refresh_observability`.
- Columns: "Severity", "Event", "Message" (same as current WarningsScreen).
- Refreshed each cycle.
- If no release_id set, show "No release selected" row.

### Screen 6: ArtifactScreen

**Purpose**: Browse extracted artifacts (top half) and run cleanup operations (bottom half).

**Widget layout**:
```python
def _content_widgets(self) -> ComposeResult:
    with Container(id="artifact-content"):
        with Vertical(id="artifact-tree-section", classes="artifact-pane"):
            yield Static("Artifacts", classes="app-title")
            yield Tree("artifacts", id="artifact-tree")
        yield Static("", id="artifact-divider")
        with Horizontal(id="artifact-cleanup-section", classes="artifact-pane"):
            yield Static("Cleanup", id="artifact-cleanup-title", classes="section-title")
            yield Static("Scope: run", id="artifact-cleanup-scope")
            yield Static("", id="artifact-cleanup-preview")
            with Horizontal(id="artifact-cleanup-buttons"):
                yield Button("Preview", id="btn-cleanup-preview", variant="default")
                yield Button("Apply", id="btn-cleanup-apply", variant="warning", disabled=True)
```

Wait — the user chose keyboard-first with single-letter keys, not buttons. Let me revise: keep the preview/apply as key bindings, remove Button widgets from compose. The actions don't need buttons when they have key bindings.

Revised layout:
```python
def _content_widgets(self) -> ComposeResult:
    with Container(id="artifact-content"):
        with Vertical(id="artifact-tree-section"):
            yield Static("Artifacts", classes="app-title")
            yield Tree("artifacts", id="artifact-tree")
        yield Static("", id="artifact-divider")
        with Vertical(id="artifact-cleanup-section"):
            yield Static("Cleanup", id="artifact-cleanup-title", classes="section-title")
            yield Static("Scope: run", id="artifact-cleanup-scope-info")
            yield Static("", id="artifact-cleanup-preview")
```

**BINDINGS**:
```python
BINDINGS = [
    Binding("y", "cleanup_preview", "Dry Run"),
    Binding("a", "cleanup_apply", "Apply"),
]
```

**Layout in TCSS**:
```css
#artifact-content {
    layout: vertical;
    height: 1fr;
}

#artifact-tree-section {
    height: 1fr;
    overflow-y: auto;
    border-bottom: solid #34324A;
}

#artifact-divider {
    height: 1;
    background: #34324A;
}

#artifact-cleanup-section {
    height: auto;
    min-height: 8;
    overflow-y: auto;
}

#artifact-tree {
    height: 1fr;
}

#artifact-cleanup-preview {
    padding: 0 0 1 0;
}
```

**Behavior**:
- `on_mount`: set scope to `"run"` (same as current CleanupScreen/ResetPreviewScreen).
- `_refresh_all`: call super, refresh artifact tree.
- `_refresh_artifacts`: port from current ArtifactsScreen — clears tree, populates from `{artifact_root}/releases/{release_id}/`.
- `action_cleanup_preview`: calls `plan_cleanup(release_id, run_id, scope=self._scope, dry_run=True)` and renders plan. Same logic as current CleanupScreen `_run_dry_run`.
- `action_cleanup_apply`: calls `apply_cleanup(release_id, run_id, scope=self._scope)`. Requires preview to have been run first (track via `self._preview_done` flag). Same logic as current CleanupScreen `_run_apply`.

**Scope**: keep simple for M25 — default `"run"`, no scope selector widget. Can be extended later.

### Screen 7: SettingsScreen

**Purpose**: Read-only config display. Unchanged from current implementation except screen info ref update.

## Removed Screens (stop registering, keep source files)

| File | Current class | Folded into |
|------|---------------|-------------|
| `screens/warnings.py` | `WarningsScreen` | ObservabilityScreen bottom 30% pane |
| `screens/event_log.py` | `EventLogScreen` | ObservabilityScreen top 70% pane |
| `screens/artifacts.py` | `ArtifactsScreen` | ArtifactScreen top pane |
| `screens/cleanup.py` | `CleanupScreen` | ArtifactScreen bottom pane |
| `screens/reset_preview.py` | `ResetPreviewScreen` | Merged with cleanup in ArtifactScreen bottom pane |

These files remain in the repo for reference but are no longer imported by `__init__.py` or `app.py`.

## Approach

Keep orchestration authority in existing domain modules:

```text
Textual screens (7)
      |
launch-control presenter/state (launch_control.py)
      |
TUIAdapter (adapter.py)
      |
extract_epub / OrchestrationRunner / tracking DB / EventBus
```

Session state:

```text
ResemanticaApp
  ├── release_id / run_id    (constructor params)
  ├── active_action          (cross-screen worker guard)
  └── session: TuiSession    (mutable, shared across screens)
        ├── input_path: Path | None
        ├── chapter_start: int | None
        └── chapter_end: int | None
```

## Stage Model

Same as previously defined — see Stage Model table in existing LLD. The `build_snapshot()` presenter in `launch_control.py` already implements this.

## Worker Model

Same as previously defined — `BaseScreen.start_worker()` with `@work(thread=True)`. The key difference: actions are now triggered by keyboard bindings instead of Button.pressed events.

Each action method calls `start_worker(action_key, callable)` which:
1. Checks `app.active_action` — if set, notifies "already running" and returns.
2. Sets `app.active_action = action_key`.
3. Spawns `@work(thread=True)` coroutine.
4. On success: clears `active_action`, calls `_refresh_all()`.
5. On failure: clears `active_action`, notifies error, calls `_refresh_all()`.

## Stage Model

(Unchanged from current LLD — see Stage Model table with 9 stages and 7 status values.)

## Data Models

(Unchanged from current LLD — `TuiSession`, `LaunchContext`, `LaunchAction`, `LaunchStageStatus`, `LaunchSnapshot`, `StageKey`, `STAGE_DEFINITIONS`, `build_snapshot()` all already implemented in `launch_control.py`.)

## Adapter Changes

(Already implemented — see current `adapter.py` with `extract_epub()`, `launch_stage()`, `launch_production()`.)

## Safety Rules

(Unchanged from current LLD — 6 rules.)

## Help Modal

Update `_build_help_text()` to show the 7-screen list and all key bindings:

```python
def _build_help_text(self) -> str:
    lines = [
        f"[b]{format_location(self._current_screen_info)}[/]",
        "",
        "[b]Screens[/]",
    ]
    for info in SCREEN_INFOS:
        current = " *" if info == self._current_screen_info else ""
        lines.append(f"{info.number} {info.title:<13} {info.purpose}{current}")
    lines.extend([
        "",
        "[b]Keys[/]",
        "1-7 Switch   ? Help   q Quit",
        "",
        "[b]Screen Keys[/]",
        "1: e=EPUB Path   p=Production   n=Next Stage",
        "2: e=Extract",
        "3: g=Glossary   s=Summaries   i=Idioms   r=Graph   b=Packets",
        "4: t=Translate   u=Rebuild",
        "5: v=Verbose   s=Source   e=Severity   f=Stage   c=Chapter   r=Refresh",
        "6: y=Dry Run   a=Apply",
    ])
    return "\n".join(lines)
```

## TCSS Changes

### New content container IDs to add to the existing rule group:

```css
#observability-content,
#artifact-content,
#ingestion-content {
    width: 1fr;
    height: 1fr;
}
```

### Add observability split-pane rules:

```css
#observability-top {
    height: 70%;
    overflow-y: auto;
    padding-right: 1;
    border-bottom: solid #34324A;
}

#observability-bottom {
    height: 30%;
    overflow-y: auto;
    padding-right: 1;
}

#observability-warnings-table {
    height: 1fr;
}
```

### Add artifact split-pane rules:

```css
#artifact-tree-section {
    height: 1fr;
    border-bottom: solid #34324A;
}

#artifact-cleanup-section {
    height: auto;
    min-height: 8;
}

#artifact-tree {
    height: 1fr;
}
```

### Add ingestion content rules:

```css
#ingestion-path,
#ingestion-status,
#ingestion-chapter-list {
    padding: 0 0 1 0;
}
```

### Add dashboard Input styling:

```css
#epub-path-input {
    width: 1fr;
    max-width: 80;
    margin: 0 0 1 0;
}
```

### Remove old content IDs:

Remove these from the existing `#*-content` rule group:
- `#warnings-content`
- `#cleanup-content`
- `#reset-preview-content`
- `#event-log-content`

Keep the existing `max-width: 118` group limited to:
```css
#dashboard-content,
#preprocessing-content,
#translation-content,
#settings-content,
#ingestion-content {
    max-width: 118;
}
```

### Remove old button container rules:

Remove `#cleanup-buttons, #reset-buttons { ... }` since those screens no longer have buttons.

### Keep observability counter/filter/event rules:

The existing rules for `#event-log-counters`, `#event-log-latest-failure`, `#event-log-filters`, `#event-log-live`, `#event-log-persisted`, `#event-log-logs` should be renamed to their `#observability-*` equivalents. Add:

```css
#observability-counters,
#observability-latest-failure,
#observability-filters,
#observability-live,
#observability-persisted,
#observability-logs {
    padding: 0 0 1 0;
    color: #D4D5F0;
}
```

## Implementation Order

### Phase 1: Navigation foundation (no visual change)

1. `navigation.py` — new 7-entry SCREEN_INFOS.
2. `screens/__init__.py` — new exports.
3. `app.py` — new SCREENS dict, BINDINGS, imports.

At this point, `1`–`7` keys should work but screens 2, 5, 6 will be missing (import errors). The old screens still exist as files.

### Phase 2: New combined screens

4. `screens/observability.py` — implement from scratch. Port top-pane logic from EventLogScreen. Add bottom-pane warnings DataTable. Full BINDINGS.
5. `screens/artifact.py` — implement from scratch. Port tree from ArtifactsScreen. Add cleanup section with key bindings `y`/`a`.
6. `screens/ingestion.py` — implement from scratch. Shows session path, extraction status, chapter list. Key binding `e` for extract.

### Phase 3: Screen modifications

7. `screens/dashboard.py` — add Input widget, BINDINGS, action methods. Keep existing rendering.
8. `screens/preprocessing.py` — remove Button widgets, add BINDINGS. Keep stage rendering.
9. `screens/translation.py` — remove Button widgets, add BINDINGS. Keep block progress.

### Phase 4: Polish

10. `screens/help.py` — update screen list + key table.
11. `screens/settings.py` — update screen info ref only.
12. `palenight.tcss` — add/remove IDs, split-pane layout rules.

### Phase 5: Verify

13. Run `ruff`, `mypy`, `pytest`.

## Tests

### Presenter tests (existing — keep passing)

- No file/release/run disables extraction and stages with clear reasons.
- Valid `.epub` path enables extraction.
- Missing extracted manifest blocks preprocessing.
- Existing extracted manifest enables first preprocessing stage.
- Running worker disables all launch actions.
- Failed latest event populates latest failure.
- Legal transition blocks out-of-order stages.

### Adapter tests (existing — keep passing)

- `extract_epub` delegates to the EPUB extractor with release id and input path.
- `launch_stage` delegates to `OrchestrationRunner.run_stage`.
- `launch_production` delegates to `OrchestrationRunner.run_production`.

### New mounted TUI tests

- Dashboard renders Input widget + disabled launch controls without release/run/file.
- Input validation: rejects non-existent path, rejects non-.epub, accepts valid path.
- Setting an EPUB path enables extraction on screens 1 and 2.
- Pressing launch key on screen 2 then screen 3 is blocked by app-level active_action guard.
- Active worker key is repeatable (same key twice shows warning, not double-launch).
- Stage failure renders latest failure without crashing.
- Observability screen shows events in top pane + warnings in bottom pane.
- Observability bottom warnings pane scrolls independently from top events pane.
- Artifact screen renders tree + cleanup section without crashing.
- Cleanup Preview/Apply work on Artifact screen.
- Settings screen remains read-only and has no launch controls.
- Screen navigation: pressing `1`–`7` switches to the correct screen.

### Test infrastructure

Create a `make_app_with_session(input_path="/tmp/test.epub", release_id="rel-1", run_id="run-1")` helper in test module to reduce boilerplate.

## Assumptions

- The existing launch_control.py module (datamodels, build_snapshot, start_worker) is already implemented and correct.
- The existing TUIAdapter with extract_epub, launch_stage, launch_production is already implemented and correct.
- Textual Input widget handles keyboard entry of the EPUB path.
- Screen-local BINDINGS do not conflict because only one screen is active at a time.
- The existing palenight.tcss theme colors are preserved — no new theme variables.
- All old screen source files (warnings.py, cleanup.py, reset_preview.py, event_log.py) remain in the repo for reference.
- Cleanup scope defaults to "run" — no scope selector widget in M25.
- Pause/cancel/resume/retry/queue are deferred to later milestones.
