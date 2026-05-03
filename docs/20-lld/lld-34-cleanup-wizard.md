# LLD 34: Cleanup Wizard TUI Screen

## Summary

Replace Screen 6's mixed artifact-tree + cleanup bottom-pane with a dedicated **Cleanup Wizard** at Screen 7. The wizard provides a 4-step guided flow (Scope → Preview → Confirm → Result) making cleanup safe, discoverable, and unambiguous via keyboard-driven interaction.

Add a `factory` scope that wipes all releases and databases across the artifact root.

## Screen Map Change

| # | Before | After |
|---|--------|-------|
| 6 | Artifact (tree + cleanup bottom pane) | Artifact (tree only) |
| 7 | Settings | **Cleanup Wizard** (NEW) |
| 8 | — | Settings |

## Wizard Steps

```
  ┌──────┐    ┌────────┐    ┌───────┐    ┌──────┐
  │Scope │──→ │Preview │──→ │Confirm│──→ │Result│
  │  1/4 │    │  2/4   │    │  3/4  │    │  4/4 │
  └──┬───┘    └───┬────┘    └───┬───┘    └──────┘
     │            │             │
     └──s──┘      │             │
                  └──────b──────┘
```

### Step 1: Scope

User selects cleanup scope via `s` key. Default: `"run"`. Cycling order:
`run` → `translation` → `preprocess` → `cache` → `all` → `factory` → `run` ...

On scope change, `plan_cleanup(dry_run=True)` is called immediately and the display shows:
- Scope name (highlighted)
- Estimated total size and item count
- Number of SQLite rows that would be deleted
- Key hints for next actions

For factory scope, a bold warning banner is shown: "This will delete ALL releases and ALL databases."

### Step 2: Preview

Groups deletable artifacts by category rather than raw path dump:

| Category | Example paths |
|----------|--------------|
| Run directory | `runs/run-abc/` |
| Translation output | `runs/run-abc/translation/` |
| Preprocess artifacts | `extracted/`, `glossary/`, `summaries/`, `idioms/`, `graph/`, `packets/` |
| Cache | `.cache/` |
| Factory — all releases | `releases/` (all releases) |
| Factory — global DB | `resemantica.db` |
| Other | any paths not matching above |

For factory scope, preserved list is empty (nothing preserved).

### Step 3: Confirm

Summary of what will be deleted:
- Total files/directories
- Estimated reclaimable space
- SQLite rows to delete
- Warning that this cannot be undone

**Factory scope** shows extra prominent warning:
```
⚠ FACTORY RESET ⚠
This will delete ALL releases, ALL runs, and ALL databases.
The entire artifact directory will be wiped clean.
```

**Apply key `a` is only enabled on this step.**

### Step 4: Result

Post-apply report:
- Files deleted (count)
- Directories deleted (count)
- SQLite rows deleted (count)
- Errors (if any)

## Scopes

| Scope | What it deletes | SQLite cleanup | Run ID needed? |
|-------|-----------------|----------------|----------------|
| `run` | One run directory | Events + state for that run | Yes |
| `translation` | Translation subdir of a run | Checkpoints for that run | Yes |
| `preprocess` | extracted/, glossary/, summaries/, idioms/, graph/, packets/ | Extracted chapters + blocks for that run | Yes |
| `cache` | `.cache/` directory | None | Yes |
| `all` | Everything in release root except tracking.db and cleanup files | All rows for that run | Yes |
| `factory` | All release directories + global `resemantica.db` | None (files deleted) | No |

## Key Bindings

### CleanupWizardScreen (screen-local)

| Key | Action | Condition |
|-----|--------|-----------|
| `s` | `cycle_scope` | Steps 1–2 |
| `p` / `→` | `preview_or_advance` | Steps 1–2 |
| `b` / `←` | `back` | Steps 2–3 |
| `a` | `confirm_and_apply` | Step 3 only |
| `Esc` | `return_to_artifact` | Always |

### Global (app.py)

| Key | Action |
|-----|--------|
| `1`–`8` | `switch_screen(...)` |
| `?` | `show_help` |
| `q` | `quit` |
| `x` | `request_stop` |

## Widget Layout

```python
def _content_widgets(self) -> ComposeResult:
    with Container(id="cleanup-wizard-content"):
        yield Static("", id="wizard-step-indicator", classes="section-title")
        yield Static("Scope: run", id="wizard-scope-info")
        yield Static("", id="wizard-main-content")
        yield Static("", id="wizard-key-hints")
```

## State Machine

```python
SCOPES = ["run", "translation", "preprocess", "cache", "all", "factory"]

class CleanupWizardScreen(BaseScreen):
    _step: int = 1        # 1-4
    _scope_index: int = 0
    _scope: str = "run"
    _plan_result: dict | None = None
    _apply_result: dict | None = None
```

### Actions

- `action_cycle_scope()`: increment `_scope_index`, update `_scope`, call `plan_cleanup()`, set `_plan_result`, re-render. Reset to step 1 if currently on step 2+.
- `action_preview_or_advance()`: if step 1, advance to step 2. If step 2, advance to step 3. If step 3+, no-op.
- `action_back()`: decrement `_step` (min 1).
- `action_confirm_and_apply()`: if step 3, call `apply_cleanup()`, store result, advance to step 4.
- `action_return_to_artifact()`: `await self.app.action_switch_screen("artifact")`.

For factory scope, `_refresh_plan()` and `action_confirm_and_apply()` do NOT require `release_id` or `run_id`.

## `cleanup.py` — Factory Scope

### `_collect_scope_artifacts`

When `scope == "factory"`:
- Ignore `release_id` and `run_id`
- Collect `{artifact_root}/releases/` (entire releases directory, all releases)
- Collect `{artifact_root}/{db_filename}` (global resemantica.db)
- Preserve nothing

### `plan_cleanup`

When `scope == "factory"`:
- Write plan to `{artifact_root}/factory_cleanup_plan.json`
- No run-specific SQLite rows (all data deleted with directories)
- `sqlite_rows` = empty list or `["ALL"]`

### `apply_cleanup`

When `scope == "factory"`:
- Read plan from `{artifact_root}/factory_cleanup_plan.json`
- Delete all collected artifacts (all releases dirs + global DB)
- No row-level SQL cleanup needed (files are gone)
- Write report to `{artifact_root}/factory_cleanup_report.json`

## Artifact Screen Changes

Remove from `artifact.py`:
- `BINDINGS` (y/a keys)
- `_scope`, `_preview_done`
- `_show_hints()`, `_update_preview()`
- `action_cleanup_preview()`, `action_cleanup_apply()`
- Cleanup section widgets from `_content_widgets()`

Keep:
- Tree browsing logic (`_refresh_artifacts`, `_populate_tree`)
- `Static`, `Tree` imports

```python
def _content_widgets(self) -> ComposeResult:
    with Container(id="artifact-content"):
        with Vertical(id="artifact-tree-section"):
            yield Static("Artifacts", classes="app-title")
            yield Tree("artifacts", id="artifact-tree")
```

## Navigation

```python
SCREEN_INFOS: tuple[ScreenInfo, ...] = (
    ScreenInfo(1, "dashboard", "DashboardScreen", "Dashboard", "Dashboard", "Run overview"),
    ScreenInfo(2, "ingestion", "IngestionScreen", "Ingestion", "Ingestion", "EPUB path and extraction"),
    ScreenInfo(3, "preprocessing", "PreprocessingScreen", "Prep", "Preprocessing", "Prepare chapters"),
    ScreenInfo(4, "translation", "TranslationScreen", "Translate", "Translation", "Translation progress"),
    ScreenInfo(5, "observability", "ObservabilityScreen", "Observe", "Observability", "Run signals and logs"),
    ScreenInfo(6, "artifact", "ArtifactScreen", "Artifact", "Artifact", "Output files"),
    ScreenInfo(7, "cleanup-wizard", "CleanupWizardScreen", "Cleanup", "Cleanup", "Scoped cleanup wizard"),
    ScreenInfo(8, "settings", "SettingsScreen", "Settings", "Settings", "Active config"),
)
```

## Help Text

```
7 Cleanup   Scoped cleanup wizard
8 Settings  Active config

Screen Keys:
...
6: (none - browse only)
7: s=Scope   p=Preview   b=Back   a=Apply   Esc=Artifact
8: (none - read-only)
```

## TCSS Additions

```css
#cleanup-wizard-content {
    width: 1fr;
    height: 1fr;
}

#wizard-step-indicator {
    color: #C792EA;
    text-style: bold;
    padding: 0 0 0 0;
}

#wizard-scope-info {
    color: #89DDFF;
    text-style: bold;
    padding: 0 0 1 0;
}

#artifact-tree-section {
    height: 1fr;
}
```

## Testing

| Test | Description |
|------|-------------|
| `test_wizard_state_machine` | Step transitions 1→2→3→4 via keys |
| `test_wizard_scope_cycle` | `s` cycles through all 6 scopes |
| `test_wizard_preview_renders_grouped` | Preview groups paths by category |
| `test_wizard_apply_guarded` | Apply on step 1 or 2 is no-op |
| `test_artifact_tree_only` | Artifact screen has no cleanup section |
| `test_navigation_8_screens` | Keys 1–8 switch screens correctly |
| `test_help_shows_8_screens` | Help modal lists 8 screens + wizard keys |
| `test_factory_scope_plan_collects_all` | Plan for factory collects releases + global DB |
| `test_factory_scope_apply_deletes_all` | Apply for factory deletes releases + global DB |
| `test_wizard_factory_scope_in_cycle` | `s` cycles to factory and back |
| `test_wizard_factory_confirm_shows_warning` | Factory confirm step shows extra warning |
