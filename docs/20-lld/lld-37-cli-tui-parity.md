# LLD 37: CLI–TUI Feature Parity

## Summary

Close 7 gaps between CLI and TUI, add a collapsible tab bar inspired by the operator's mockup, and unify all progress indicators to consistent `▓░` block-style completion bars. The TUI becomes a standalone operator surface for all pipeline workflows with keyboard-driven chapter scoping, resume, force/dry-run toggles, batched ordering, and config loading.

## Screen Map (8 Screens)

| # | Screen | Screen ID | Class | Short | Label | Sub-tabs |
|---|--------|-----------|-------|-------|-------|----------|
| 1 | Dashboard | `dashboard` | `DashboardScreen` | `D` | `Dashboard` | `()` |
| 2 | Ingestion | `ingestion` | `IngestionScreen` | `I` | `Ingestion` | `()` |
| 3 | Preprocess | `preprocessing` | `PreprocessingScreen` | `P` | `Preprocess` | `(Glossary, Summaries, Idioms, Graph, Packets)` |
| 4 | Translation | `translation` | `TranslationScreen` | `T` | `Translate` | `(Pass 1, Pass 2, Pass 3, Rebuild)` |
| 5 | Observability | `observability` | `ObservabilityScreen` | `O` | `Observe` | `()` |
| 6 | Artifact | `artifact` | `ArtifactScreen` | `A` | `Artifact` | `()` |
| 7 | Cleanup | `cleanup-wizard` | `CleanupWizardScreen` | `C` | `Cleanup` | `()` |
| 8 | Settings | `settings` | `SettingsScreen` | `S` | `Settings` | `()` |

## Part 1: Collapsible Tab Bar

### ScreenInfo Changes (`navigation.py`)

```python
@dataclass(frozen=True)
class ScreenInfo:
    number: int
    screen_id: str
    class_name: str
    short_label: str          # NEW: 1-char label for collapsed state
    label: str                # existing
    title: str                # existing
    purpose: str              # existing
    sub_tabs: tuple[str, ...] = ()  # NEW: sub-tab labels

SCREEN_INFOS: tuple[ScreenInfo, ...] = (
    ScreenInfo(1, "dashboard", "DashboardScreen", "D", "Dashboard", "Dashboard", "Run overview"),
    ScreenInfo(2, "ingestion", "IngestionScreen", "I", "Ingestion", "Ingestion", "EPUB path and extraction"),
    ScreenInfo(3, "preprocessing", "PreprocessingScreen", "P", "Preprocess", "Preprocessing", "Prepare chapters",
               ("Glossary", "Summaries", "Idioms", "Graph", "Packets")),
    ScreenInfo(4, "translation", "TranslationScreen", "T", "Translate", "Translation", "Translation progress",
               ("Pass 1", "Pass 2", "Pass 3", "Rebuild")),
    ScreenInfo(5, "observability", "ObservabilityScreen", "O", "Observe", "Observability", "Run signals and logs"),
    ScreenInfo(6, "artifact", "ArtifactScreen", "A", "Artifact", "Artifact", "Output files"),
    ScreenInfo(7, "cleanup-wizard", "CleanupWizardScreen", "C", "Cleanup", "Cleanup", "Scoped cleanup wizard"),
    ScreenInfo(8, "settings", "SettingsScreen", "S", "Settings", "Settings", "Active config"),
)
```

### Tab Bar Format

```python
def format_tab_bar(active_info: ScreenInfo | None) -> str:
    """Render collapsible tab bar. Active screen shows full name + sub-tabs.
    Inactive screens collapse to [N]short_label."""
    parts: list[str] = [" "]
    for info in SCREEN_INFOS:
        if info == active_info:
            parts.append(f"[b][{info.number} {info.label}][/]")
            if info.sub_tabs:
                sub = " · ".join(
                    f"[{t}]" if i == 0 else t for i, t in enumerate(info.sub_tabs)
                )
                parts.append(f" {sub}")
        else:
            parts.append(f"[dim][{info.number}]{info.short_label}[/]")
    return "  ".join(parts)
```

When on screen 3:
```
 [1]D  [2]I  [b][3 Preprocess][/] [Glossary] · Summaries · Idioms · Graph · Packets  [4]T  [5]O  [6]A  [7]C  [8]S
```

When on screen 1:
```
 [b][1 Dashboard][/]  [2]I  [3]P  [4]T  [5]O  [6]A  [7]C  [8]S
```

### BaseScreen Layout Change

Replace the current 1-row header with 2 rows:

```python
def compose(self) -> ComposeResult:
    yield Horizontal(Static(id="tab-bar"), id="tab-bar-container")
    yield Horizontal(
        Static(id="pulse-bar"),
        Static(id="status-run-info"),
        Static(id="status-chapter-progress"),
        Static(id="status-pass"),
        id="status-bar-container",
    )
    yield Vertical(
        Static("Chapter Spine", id="spine-title"),
        OptionList(id="spine-items"),
        id="spine-container",
        classes="spine",
    )
    with Container(id="main-content"):
        yield from self._content_widgets()
    yield Horizontal(
        Static(id="footer-block-progress"),
        Static(id="footer-warnings"),
        Static(id="footer-failures"),
        Static(id="footer-elapsed"),
        Static(id="footer-keys"),
        id="footer-container",
        classes="footer-bar",
    )
```

Removed from header: `#header-screen-location` (replaced by tab bar), `#header-run-info` (moved to `#status-run-info`), `#header-chapter-progress` (moved to `#status-chapter-progress`), `#header-pass` (moved to `#status-pass`).

### Tab Bar Refresh

```python
def _render_tab_bar(self) -> None:
    info = screen_info_for_class_name(self.__class__.__name__)
    bar = self.query_one("#tab-bar", Static)
    bar.update(format_tab_bar(info))
```

Called from:
- `on_mount()` — initial render
- `app.py` screen switch handler — call on target screen after push
- `_refresh_all()` — periodic refresh

### App.py Changes

```python
async def action_switch_screen(self, screen_id: str) -> None:
    await self.push_screen(screen_id)
    # Render tab bar on the newly active screen
    screen = self.screen
    render_tab_bar = getattr(screen, "_render_tab_bar", None)
    if callable(render_tab_bar):
        render_tab_bar()
```

### TCSS for Tab Bar / Status Bar

```css
#tab-bar-container {
    layout: horizontal;
    height: 1;
    background: #1E1F2B;
}

#tab-bar {
    width: 1fr;
    color: #D4D5F0;
}

#status-bar-container {
    layout: horizontal;
    height: 1;
}

#status-run-info {
    width: 1fr;
    color: #EEFFFF;
}

#status-chapter-progress {
    width: 20;
    color: #D4D5F0;
}

#status-pass {
    width: 14;
    color: #89DDFF;
}
```

## Part 2: Progress Bar Consistency

### Character Mapping

| Before | After | Context |
|--------|-------|---------|
| `━` (U+2501) | `▓` (U+2593) | Filled bar segment |
| `┺` (U+257A) | `▒` (U+2592) | Active marker |
| `─` (U+2500) | `░` (U+2591) | Empty bar segment |
| `▁▂▃▄▅▆▇█` | Keep as-is | Pulse bar sparkline |
| `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` | Keep as-is | Braille spinner |

### Helper Methods

```python
_PROGRESS_BAR_FILLED = "\u2593"   # ▓
_PROGRESS_BAR_ACTIVE = "\u2592"   # ▒
_PROGRESS_BAR_EMPTY = "\u2591"    # ░

@staticmethod
def _render_scoped_bar(model: StageProgress, status: str, width: int = 20) -> str:
    total = max(1, model.total or 0)
    completed = min(max(0, model.completed), total)
    if completed >= total:
        return f"[green]{_PROGRESS_BAR_FILLED * width}[/]"
    filled = int((completed / total) * width)
    has_active = model.active_chapter is not None or status == "running"
    marker = _PROGRESS_BAR_ACTIVE if has_active else _PROGRESS_BAR_EMPTY
    empty = max(0, width - filled - (1 if has_active else 0))
    color = "cyan" if status == "running" or has_active else "comment"
    filled_text = _PROGRESS_BAR_FILLED * filled
    marker_text = marker if has_active else ""
    empty_text = _PROGRESS_BAR_EMPTY * empty
    return f"[{color}]{filled_text}{marker_text}{empty_text}[/]"

@staticmethod
def _static_bar(*, color: str, fill: str | None = None, width: int = 20) -> str:
    char = fill or _PROGRESS_BAR_FILLED
    return f"[{color}]{char * width}[/]"

@staticmethod
def _running_bar(*, color: str, width: int = 20) -> str:
    filled = _PROGRESS_BAR_FILLED * 8
    marker = _PROGRESS_BAR_ACTIVE
    remaining = _PROGRESS_BAR_EMPTY * (width - 9)
    return f"[{color}]{filled}{marker}{remaining}[/]"
```

### Header Chapter Progress

```python
@classmethod
def _format_chapter_progress(cls, *, total_chapters: int, checkpoint: dict | None = None) -> str:
    current = cls._chapter_index_from_checkpoint(checkpoint)
    bar_width = 10
    if current == 0 or total_chapters == 0:
        bar = _PROGRESS_BAR_EMPTY * bar_width
    else:
        filled = int((current / max(1, total_chapters)) * bar_width)
        bar = _PROGRESS_BAR_FILLED * filled + _PROGRESS_BAR_EMPTY * (bar_width - filled)
    return f"{bar} Ch {current}/{max(0, total_chapters)}"
```

### Footer Block Progress

In `_update_footer`:
```python
bar_width = 16
if total_blocks > 0:
    filled = int((completed_blocks / total_blocks) * bar_width)
    bar = _PROGRESS_BAR_FILLED * filled + _PROGRESS_BAR_EMPTY * (bar_width - filled)
else:
    bar = _PROGRESS_BAR_EMPTY * bar_width
metrics["block_progress"] = f"{bar} {completed_blocks}/{total_blocks} blk"
```

TCSS width change: `#footer-block-progress { width: 28; }` (was 20 — needs room for 16 bar + count).

## Part 3: Dashboard Changes

### Widget Layout

```python
def _content_widgets(self) -> ComposeResult:
    with Container(id="dashboard-content"):
        yield Static("Dashboard", classes="app-title")
        yield Static("", id="dashboard-session-info")
        yield Static("", id="dashboard-chapter-scope")
        yield Static("", id="dashboard-stage-list")
        yield Static("", id="dashboard-active-worker")
        yield Static("", id="dashboard-latest-failure")
        yield Static("", id="dashboard-recent-runs")
```

### Chapter Scope Input Fields

Add two Input widgets in compose — but only when the operator activates them via a key, to keep the layout clean:

```python
BINDINGS = [
    Binding("c", "toggle_chapter_scope", "Scope", priority=True),
    Binding("p", "launch_production", "Production"),
    Binding("n", "launch_next", "Next Stage"),
    Binding("f", "toggle_force", "Force"),
    Binding("d", "toggle_dry_run", "Dry-Run"),
    Binding("r", "resume_run", "Resume"),
]
```

`action_toggle_chapter_scope` toggles visibility of a `Horizontal` container with two Inputs (chapter-start, chapter-end). On `Input.Submitted`, validates and stores in `TuiSession`.

Alternative: Always show the Inputs if not yet set. Keep it simple:

```python
yield Horizontal(
    Input(placeholder="From Ch", id="chapter-start-input", type="integer"),
    Input(placeholder="To Ch", id="chapter-end-input", type="integer"),
    id="dashboard-scope-inputs",
)
```

On `Input.Submitted` for either field:
```python
def _on_chapter_input_submitted(self, message: Input.Submitted) -> None:
    try:
        val = int(message.value) if message.value.strip() else None
    except ValueError:
        self.notify("Invalid chapter number", severity="error")
        return
    if message.input.id == "chapter-start-input":
        self.app.session.chapter_start = val
    elif message.input.id == "chapter-end-input":
        self.app.session.chapter_end = val
```

### Force Toggle

```python
def action_toggle_force(self) -> None:
    self._force = not getattr(self, "_force", False)
    status = "ON" if self._force else "OFF"
    self.notify(f"Force re-run: {status}")
```

Passed through to `adapter.launch_production(force=self._force)`.

### Dry-Run Toggle

```python
def action_toggle_dry_run(self) -> None:
    self._dry_run = not getattr(self, "_dry_run", False)
    status = "ON" if self._dry_run else "OFF"
    self.notify(f"Dry-run mode: {status}")
```

Passed through to `adapter.launch_production(dry_run=self._dry_run)`.

### Resume Run

```python
def action_resume_run(self) -> None:
    runs = self._get_recent_runs()
    if not runs:
        self.notify("No recent runs to resume", severity="warning")
        return
    # For now: resume most recent run
    run = runs[0]
    self.start_worker(
        f"resume-{run.run_id}",
        lambda: adapter.resume_run(release_id=run.release_id, run_id=run.run_id),
    )
```

`_get_recent_runs()` queries the tracking DB for the 5 most recent runs.

## Part 4: Preprocess Screen Changes

### Key Bindings

```python
BINDINGS = [
    Binding("d", "launch_glossary_discover", "Gloss-Disc"),
    Binding("t", "launch_glossary_translate", "Gloss-Trans"),
    Binding("p", "launch_glossary_promote", "Gloss-Prom"),
    Binding("s", "launch_summaries", "Summaries"),
    Binding("i", "launch_idioms", "Idioms"),
    Binding("r", "launch_graph", "Graph"),
    Binding("b", "launch_packets", "Packets"),
]
```

### Action Methods

Each action calls `_launch_stage(stage_key)`. Stage keys:

| Key | Stage key | CLI equivalent |
|-----|-----------|---------------|
| `d` | `preprocess-glossary` (discover phase) | `rsem pre glossary-discover` |
| `t` | `preprocess-glossary` (translate phase) | `rsem pre glossary-translate` |
| `p` | `preprocess-glossary` (promote phase) | `rsem pre glossary-promote` |
| `s` | `preprocess-summaries` | `rsem pre summaries` |
| `i` | `preprocess-idioms` | `rsem pre idioms` |
| `r` | `preprocess-graph` | `rsem pre graph` |
| `b` | `packets-build` | `rsem packets build` |

Note: `d`, `t`, `p` all target `preprocess-glossary` — the stage pipeline handles phase selection internally based on checkpoint state. The TUI just launches and shows status. If a phase is already complete, launching again with `f` (force from Dashboard) will re-run it.

### Simplified Stage List

The `_render_stages_from_snapshot` already shows per-phase progress for glossary (discover/translate/promote). The only change is removing unused keys and ensuring the key hint line matches:

```python
lines.append("[dim]d[/]=Disc  [dim]t[/]=Trans  [dim]p[/]=Prom  [dim]s[/]=Sum  [dim]i[/]=Idioms  [dim]r[/]=Graph  [dim]b[/]=Packets")
```

## Part 5: Translation Screen Changes

### Add Batched Toggle

```python
BINDINGS = [
    Binding("t", "launch_translate", "Translate"),
    Binding("u", "launch_rebuild", "Rebuild"),
    Binding("b", "toggle_batched", "Batched"),
]
```

```python
def action_toggle_batched(self) -> None:
    self._batched = not getattr(self, "_batched", False)
    status = "BATCHED" if self._batched else "SEQUENTIAL"
    self.notify(f"Mode: {status}")
```

Render toggle state in the stage list:

```python
mode = "BATCHED" if self._batched else "SEQUENTIAL"
lines.append(f"Mode: [{'cyan' if self._batched else 'comment'}]{mode}[/]  [dim]b[/]=toggle")
```

When batched is active, `action_launch_translate` passes `batched=True` to `adapter.launch_stage("translate-range", batched=True)`.

## Part 6: Settings Screen Changes

### Add Config Load

```python
def _content_widgets(self) -> ComposeResult:
    with Container(id="settings-content"):
        yield Static("Settings", classes="app-title")
        yield Static("", id="settings-active-config")
        yield Input(placeholder="/path/to/config.toml", id="config-path-input")
        yield Static("", id="settings-config-display")

BINDINGS = [
    Binding("l", "load_config", "Load"),
]
```

```python
def action_load_config(self) -> None:
    path_str = self.query_one("#config-path-input", Input).value
    if not path_str.strip():
        self.notify("No path entered", severity="warning")
        return
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        self.notify(f"Config not found: {path}", severity="error")
        return
    if path.suffix != ".toml":
        self.notify("Config must be .toml file", severity="error")
        return
    self.app._config_path = path
    self.notify(f"Config loaded: {path}")
    self._refresh_all()
```

## Part 7: Preprocess Stage Pipeline Consideration

The current preprocess pipeline resolves stages internally — launching `preprocess-glossary` runs discover/translate/promote in sequence based on checkpoint state. The TUI keys `d`/`t`/`p` all launch `preprocess-glossary`; the pipeline picks the right phase.

However, the operator needs explicit phase control (not all phases auto-advance). The keys serve as explicit phase targeting:

- `d` → launches glossary with target phase "discover"
- `t` → launches glossary with target phase "translate" (requires discover done)
- `p` → launches glossary with target phase "promote" (requires translate done)

The adapter method signature:
```python
def launch_stage(
    self,
    stage_key: str,
    *,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    batched: bool = False,
    phase: str | None = None,  # NEW: "discover" | "translate" | "promote" | None
) -> dict[str, Any]: ...
```

When `phase` is set, it's passed to the orchestration runner which uses it to skip completed phases.

## Full Key Binding Reference

| Screen | Keys | Actions |
|--------|------|---------|
| 1 Dashboard | `c` chapter scope toggle, `f` force, `d` dry-run, `p` production, `n` next stage, `r` resume | 6 keys |
| 2 Ingestion | `e` extract | 1 key |
| 3 Preprocess | `d` gloss-disc, `t` gloss-trans, `p` gloss-prom, `s` summaries, `i` idioms, `r` graph, `b` packets | 7 keys |
| 4 Translation | `t` translate, `u` rebuild, `b` batched toggle | 3 keys |
| 5 Observability | `v` verbosity, `s` source, `e` severity, `f` stage filter, `c` chapter filter, `r` refresh | 6 keys |
| 6 Artifact | `y` dry-run preview, `a` apply | 2 keys |
| 7 Cleanup | (wizard internal: `s` scope, `p` preview, `b` back, `a` apply) | 4 keys |
| 8 Settings | `l` load config | 1 key |

## Help Modal

Update `_build_help_text`:

```python
def _build_help_text(self) -> str:
    lines = [f"[b]{format_location(self._current_screen_info)}[/]", ""]
    lines.append("[b]Screens[/]")
    for info in SCREEN_INFOS:
        current = " *" if info == self._current_screen_info else ""
        lines.append(f"{info.number} {info.title:<13} {info.purpose}{current}")
    lines.extend([
        "", "[b]Keys[/]", "1-8 Switch   ? Help   q Quit", "",
        "[b]Dashboard[/]",
        "c=Scope   f=Force   d=Dry-Run   p=Production   n=Next   r=Resume",
        "[b]Ingestion[/]",
        "e=Extract",
        "[b]Preprocess[/]",
        "d=Disc   t=Trans   p=Prom   s=Sum   i=Idioms   r=Graph   b=Packets",
        "[b]Translation[/]",
        "t=Translate   u=Rebuild   b=Batched",
        "[b]Observability[/]",
        "v=Verbose   s=Source   e=Severity   f=Stage   c=Chapter   r=Refresh",
        "[b]Artifact[/]",
        "y=Dry Run   a=Apply",
        "[b]Cleanup[/]",
        "s=Scope   p=Preview   b=Back   a=Apply",
        "[b]Settings[/]",
        "l=Load Config",
    ])
    return "\n".join(lines)
```

## Implementation Order

### Phase 1: Foundation

1. `navigation.py` — add `short_label`, `sub_tabs` fields; update `ScreenInfo`; add `format_tab_bar()`
2. `screens/base.py` — split header into tab-bar + status-bar; add `_render_tab_bar()`

At this point the tab bar renders but content is unchanged.

### Phase 2: Progress Bar Consistency

3. `screens/base.py` — update `_render_scoped_bar`, `_static_bar`, `_running_bar` to use `▓░▒`
4. `screens/base.py` — update `_format_chapter_progress` to include bar
5. `screens/base.py` — update footer block progress to use bar
6. `palenight.tcss` — widen `#footer-block-progress` to 28

### Phase 3: Dashboard

7. `screens/dashboard.py` — add chapter-scope Inputs, force/dry-run/resume bindings

### Phase 4: Per-Screen Changes

8. `screens/preprocessing.py` — add 7-key bindings, update hint line
9. `screens/translation.py` — add batched toggle binding
10. `screens/settings.py` — add config-path Input + load binding

### Phase 5: Polish

11. `screens/help.py` — update screen list + key table
12. `app.py` — wire tab bar refresh on screen switch

### Phase 6: Verify

13. Run `ruff`, `mypy`, `pytest`

## Tests

- Unit: `format_tab_bar` renders correctly for active/inactive screens
- Unit: `_format_chapter_progress` returns `"▓▓▓░░░░░ Ch 5/20"` format
- Unit: `_render_scoped_bar` uses `▓░` characters
- Unit: footer block progress uses `▓░` characters
- Unit: Dashboard Input validation for chapter numbers
- Unit: Preprocess 7 action methods call correct stage keys
- Unit: Translation batched toggle state
- Unit: Settings config load validation

## Decisions

| Decision | Alternative | Rationale |
|----------|-----------|-----------|
| Tab bar in header vs separate row | Merged into header | Simplifies compose without adding a new top-level widget |
| `▓░▒` for progress bars | Keep `━┺─` | User preferred block characters for consistency |
| Phase targeting via `phase` param | Single launch for all | Explicit phase control needed for operator workflow |
| Resume = most recent run | Resume picker UI | Most-recent is simplest for M28; can be extended |
