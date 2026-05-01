# LLD 27: Dashboard Session Initialization

## Summary

Replace the Dashboard's free-form `Input` field for EPUB path entry with two curated action buttons — **New File** and **Resume Run** — accessed via arrow-key navigation and Enter. Each button opens a dedicated modal dialog that collects the required session identifiers (release, run, and optionally file path) before stage launch is possible.

The existing `on_input_submitted` flow is replaced by a `ListView`-based action selector. Session state is still stored on `ResemanticaApp.session` and `ResemanticaApp._release_id` / `_run_id`.

## Public Interfaces

### `dashboard.py` — action list

```
DashboardScreen._content_widgets() yields, in place of Input:
  ListView(ListItem("New File"), ListItem("Resume Run"), id="dashboard-action-list")
```

Arrow keys navigate the list; Enter triggers the selected action. No `Input` widget is mounted on the Dashboard.

Bindings change:

| Old | New | Action |
|-----|-----|--------|
| `e` / `escape` | removed | No focus/blur needed for a list |
| `p` / `n` | kept | Production / Next Stage |

Keyboard number keys (1–7) for screen switching are **unchanged** — they bypass the list selection.

### `run_dialog.py` — two modal dialogs

**`NewFileDialog(ModalScreen[tuple[Path, str, str] | None])`**

Three input fields stacked vertically:

| Widget | ID | Purpose | Validation |
|--------|----|---------|------------|
| `Input` | `path-input` | `.epub` file path | Must exist, be readable, end in `.epub` |
| `Input` | `release-input` | Release identifier | Must be non-empty |
| `Input` | `run-input` | Run identifier | Must be non-empty |

Buttons: `Submit` (primary), `Cancel`.

On submit: validates all three fields, returns `(Path, release_str, run_str)`. On cancel: returns `None`.

**`ResumeRunDialog(ModalScreen[tuple[str, str] | None])`**

Two input fields:

| Widget | ID | Purpose | Validation |
|--------|----|---------|------------|
| `Input` | `release-input` | Release identifier | Must be non-empty |
| `Input` | `run-input` | Run identifier | Must be non-empty |

Buttons: `Submit` (primary), `Cancel`.

On submit: validates both fields, returns `(release_str, run_str)`. Clears `session.input_path` to prevent stale-file extraction.

### `app.py` — session identifier mutation

```python
def set_ids(self, release_id: str, run_id: str) -> None:
    """Set release and run identifiers. Called after dialog submission."""
    self._release_id = release_id
    self._run_id = run_id
```

## Data Sources

| Data | Source | Set By |
|------|--------|--------|
| `release_id` | `ResemanticaApp._release_id` | CLI `--release` flag, or dialog submission via `set_ids()` |
| `run_id` | `ResemanticaApp._run_id` | CLI `--run` flag, or dialog submission via `set_ids()` |
| `input_path` | `TuiSession.input_path` | "New File" dialog submission only; cleared by "Resume Run" dialog |

## UX / UI Design

### Aesthetic Direction

**Industrial Terminal** — two unadorned action items in a compact list, no decoration. Modal dialogs are tight, left-aligned, validation-feedback is inline via `notify()`. The design prioritizes keyboard ergonomics (up/down to select, Enter to confirm) over visual chrome. This fits the existing palenight dark theme (`#292D3E` background, `#1E1F2B` containers, `#82AAFF` borders).

### DFII Assessment

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| Aesthetic Impact | 3 | Terminal-native; not flashy but honest |
| Context Fit | 5 | Directly solves user workflow; no scope creep |
| Implementation Feasibility | 5 | Reuses existing `ModalScreen`, `ListView`, `Container` patterns |
| Performance Safety | 5 | No polling, no animation; dialogs are push/pop |
| Consistency Risk | -2 | New dialog pattern extends modal convention from HelpScreen; no architectural drift |

**DFII = (3+5+5+5) - 2 = 16** → Execute fully.

### Differentiation Anchor

The action list replaces a bare text input with a two-choice decision point. This avoids the generic "type a path" pattern by forcing an explicit intent declaration upfront: *am I starting fresh or resuming?*

### Navigation & Focus Flow

```
Dashboard mount
  └─ ListView auto-focuses first item ("New File")
       ├─ Up/Down  → cycle between items
       └─ Enter    → push corresponding dialog

NewFileDialog modal
  └─ Tab cycles: path → release → run → Submit → Cancel → path
       └─ Enter on Submit → validate → dismiss → callback sets session + IDs
       └─ Enter on Cancel → dismiss (None) → nothing changes

ResumeRunDialog modal
  └─ Tab cycles: release → run → Submit → Cancel → release
       └─ Enter on Submit → validate → dismiss → callback sets IDs
       └─ Enter on Cancel → dismiss (None) → nothing changes
```

### Dialog Layout

Both dialogs follow the `HelpScreen` pattern:

```
┌──────────────────────────────────────┐
│  ◆ New File                          │  ← title, accent color (#C792EA)
│                                      │
│  File path                           │  ← label, dim
│  ┌────────────────────────────────┐  │
│  │ /path/to/book.epub            │  │  ← Input
│  └────────────────────────────────┘  │
│                                      │
│  Release ID                          │
│  ┌────────────────────────────────┐  │
│  │ v3.2                          │  │  ← Input
│  └────────────────────────────────┘  │
│                                      │
│  Run ID                              │
│  ┌────────────────────────────────┐  │
│  │ run-1                         │  │  ← Input
│  └────────────────────────────────┘  │
│                                      │
│  [ Submit ]  [ Cancel ]              │  ← Button row
└──────────────────────────────────────┘
```

The Resume Run dialog omits the file path section.

### Color Usage (Palenight palette)

| Element | Color | CSS Variable Equivalent |
|---------|-------|------------------------|
| Dialog background | `#1E1F2B` | — |
| Dialog border | `#82AAFF` | — |
| Title | `#C792EA` | — |
| Input labels | `#676E95` | `.dimmed` |
| Input text | `#EEFFFF` | `.bright` |
| Submit button | `#82AAFF` | `.key-value-key` |
| Cancel button | `#676E95` | `.dimmed` |

### Differentiation Callout

This avoids generic "type a path" entry by replacing the unbounded input with two **curated actions** that each set an explicit session scope. The user declares intent (new or resume) before filling details, preventing the ambiguous "I typed a path but what about release/run?" state.

## Dialog Specifications

### NewFileDialog — validation rules

1. **Path required**: non-empty string
2. **Path exists**: `Path.expanduser().resolve().exists()` must be true
3. **Path is file**: `.is_file()` must be true
4. **Path is .epub**: `.suffix.lower() == '.epub'` must be true
5. **Path readable**: `open(path, 'rb')` in try/except must not raise `PermissionError`
6. **Release required**: stripped string length > 0
7. **Run required**: stripped string length > 0

On any validation failure: `self.notify("message", severity="error")`, stay on dialog.

### ResumeRunDialog — validation rules

1. **Release required**: stripped string length > 0
2. **Run required**: stripped string length > 0

On any validation failure: `self.notify("message", severity="error")`, stay on dialog.

### Post-submission callback

```
if result is not None:
    app.set_ids(release_id=result[1], run_id=result[2])   # NewFile: (path, rel, run)
    app.set_ids(release_id=result[0], run_id=result[1])   # ResumeRun: (rel, run)
    app.session.input_path = result[0]   # NewFile only
    # ResumeRun: session.input_path = None (cleared)
    notify("Release: X, Run: Y")
else:
    notify("Session not initialized", severity="warning")

self._refresh_dashboard()
```

## Session State Transitions

```
State 1: No session
  release_id=None, run_id=None, input_path=None
  → User picks "New File" → fills dialog → State 2
  → User picks "Resume Run" → fills dialog → State 3

State 2: New file session
  release_id="v3.2", run_id="run-1", input_path="/path/to/book.epub"
  → User picks "Resume Run" → fills dialog → State 3 (input_path cleared)

State 3: Resume session
  release_id="v2.1", run_id="production", input_path=None
  → User picks "New File" → fills dialog → State 2 (input_path set)

State 4: CLI-preconfigured
  release_id="foo", run_id="bar", input_path=None
  → Actions shown but dialog also works (overrides existing IDs)
```

## Error Scenarios

| Scenario | Behaviour |
|----------|-----------|
| Dialog dismissed (Escape / Cancel) | No state change, `notify("Session not initialised", severity="warning")` |
| New File: path empty | `notify("File path is required", severity="error")`, stay on dialog |
| New File: path not .epub | `notify("Path must be an .epub file", severity="error")`, stay on dialog |
| New File: path unreadable | `notify("File not readable: {path}", severity="error")`, stay on dialog |
| Either dialog: release empty | `notify("Release ID is required", severity="error")`, stay on dialog |
| Either dialog: run empty | `notify("Run ID is required", severity="error")`, stay on dialog |
| Stage launch with no session | Existing guard: `_make_adapter()` returns `None` → `"Cannot launch: release/run not set"` |
| CLI flags + dialog override | Dialog submission overwrites — explicit user action wins |
