# LLD 12: TUI Layout Specification

## Summary

Define the visual layout, screen architecture, color system, widget structure, and interaction model for the Resemantica Textual TUI. This document specifies *what the operator sees and how they navigate*; the parent LLD (`lld-12-cli-and-tui.md`) specifies *what the TUI connects to*.

Design direction: **Industrial Manuscript Control** — a hybrid of industrial utilitarian telemetry and editorial chapter navigation. Dense status on the right, book-like chapter spine on the left.

DFII score: 16 (Impact 4 + Fit 5 + Feasibility 4 + Performance 5 − Consistency Risk 2).

Differentiation anchor: the **pulse bar** — a live horizontal sparkline at the top of every screen showing pipeline throughput (blocks translated per minute). Flat when idle, pulsing cyan when active, spiking red on retries. The operator can gauge system health in under one second without reading any text.

## Cross-References

- Parent LLD: `lld-12-cli-and-tui.md`
- Event types consumed: `lld-10-orchestration-events.md`
- Metrics displayed in dashboard: `lld-13-observability.md`
- Phase model and lifecycle: `../10-architecture/runtime-lifecycle.md`
- Event stream and artifact fields: `../../DATA_CONTRACT.md`
- Risk score formula: `lld-09-pass3-and-risk.md`
- Storage topology: `../10-architecture/storage-topology.md`

---

## Design System

### Color Palette — Material Palenight

Source: ansicolor.com "Palenight" theme. All colors are specified as hex values and rendered via Textual CSS with ANSI truecolor escapes. This ensures the palette is independent of the user's terminal theme.

| Token | Hex | Role |
|-------|-----|------|
| `bg` | `#292D3E` | App background |
| `bg-darker` | `#1E1F2B` | Chapter spine, header bar, footer bar |
| `bg-lighter` | `#34324A` | Selected items, hovered rows, focused widgets |
| `fg` | `#D4D5F0` | Primary text |
| `fg-bright` | `#EEFFFF` | Headings, emphasis, active labels |
| `comment` | `#676E95` | Dimmed text, secondary labels, timestamps |
| `red` | `#FF5370` | Failures, hard stops, error severity |
| `orange` | `#F78C6C` | Warnings, retries, serious severity |
| `yellow` | `#FFCB6B` | Working/provisional state, informational flags |
| `green` | `#C3E88D` | Completed stages, authority state, success |
| `cyan` | `#89DDFF` | Active/in-progress, pulse bar (normal), current pass |
| `blue` | `#82AAFF` | Navigation highlights, selected chapter, links |
| `purple` | `#C792EA` | Metrics, counts, stat values |
| `magenta` | `#BB80B3` | Glossary entries, entity references |

### Semantic Color Mapping

| Semantic Role | Token | Color |
|---------------|-------|-------|
| Status: not started | `comment` | `#676E95` |
| Status: in progress | `cyan` | `#89DDFF` |
| Status: completed | `green` | `#C3E88D` |
| Status: failed | `red` | `#FF5370` |
| Status: high-risk | `orange` | `#F78C6C` |
| Authority state | `green` | `#C3E88D` |
| Working state | `yellow` | `#FFCB6B` |
| Operational state | `comment` | `#676E95` |
| Pulse: active | `cyan` | `#89DDFF` |
| Pulse: idle | `comment` | `#676E95` |
| Pulse: error/retry | `red` | `#FF5370` |

### Typography

The TUI is terminal-native. All text is monospaced. Hierarchy is expressed through:

- **Bold** for screen titles and key labels
- `fg-bright` for headings
- `fg` for body text
- `comment` for secondary text
- Scale: heading = default size, body = default size, dimmed = default size — differentiation is purely through color and weight, not font size

### Spacing Rhythm

- Widget padding: 1 cell on all sides
- Between major sections: 1 blank row
- Chapter spine items: single-row height, no internal padding
- Footer/status bar: single-row height, separated by horizontal rules

### Motion Philosophy

Motion is sparse and purposeful:

- Pulse bar updates every 5 seconds (sparkline redraw)
- Chapter spine indicators transition on state change (no animation)
- Warning count in footer flashes `orange` for 2 seconds on new warning arrival
- No decorative micro-motion

---

## App Shell

The shell is constant across all screens. Only the **main content area** changes.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Pulse Bar: ▁▂▃▅▇█▇▅▃▂▁   Run: r-001   Ch 12/50   █ PASS 2      │  HEADER (1 row)
├──────────┬──────────────────────────────────────────────────────────┤
│          │                                                          │
│ Chapter  │   Main Content Area                                     │
│ Spine    │   (changes per screen)                                  │
│          │                                                          │
│  ▸ Ch 1  │                                                          │
│  ■ Ch 2  │                                                          │
│  ■ Ch 3  │                                                          │
│  □ Ch 4  │                                                          │
│  □ Ch 5  │                                                          │
│  ...     │                                                          │
│          │                                                          │
├──────────┴──────────────────────────────────────────────────────────┤
│  142/350 blocks │ 3 warnings │ 0 failures │ 0:23:41  [1-7:?] [q]  │  FOOTER (1 row)
└─────────────────────────────────────────────────────────────────────┘
```

### Header Bar

Height: 1 row. Background: `bg-darker`. Contains:

| Section | Content | Color |
|---------|---------|-------|
| Pulse sparkline | 30-char ASCII sparkline of blocks/min | `cyan` / `comment` / `red` |
| Run ID | Current run identifier | `fg-bright` |
| Chapter progress | `Ch N/M` | `fg` |
| Current pass | Pass indicator: `PASS 1`, `PASS 2`, `PASS 3`, `IDLE`, `PREPROCESS` | `cyan` when active, `comment` when idle |

### Chapter Spine

Width: 18 chars. Background: `bg-darker`. Scrollable vertical list of chapter tiles.

Each tile is one row: `<status_char> Ch <number>`

Status characters:

| Char | Meaning | Color |
|------|---------|-------|
| `□` | Not started | `comment` |
| `▸` | In progress | `cyan` |
| `■` | Complete | `green` |
| `✗` | Failed | `red` |
| `◈` | High-risk chapter | `orange` |

The currently selected chapter is highlighted with `bg-lighter` background and `blue` foreground. The spine scrolls to keep the active chapter visible.

Navigation: `↑`/`↓` moves selection, `Enter` drills into the chapter detail (switches to Translation screen if not already there).

### Footer Bar

Height: 1 row. Background: `bg-darker`. Contains:

| Section | Content | Color |
|---------|---------|-------|
| Block progress | `N/M blocks` | `fg` |
| Warning count | `N warnings` | `orange` if > 0, else `comment` |
| Failure count | `N failures` | `red` if > 0, else `comment` |
| Elapsed time | `H:MM:SS` | `fg` |
| Keybinding hint | `[1-7:?] [q]` | `comment` |

---

## Screen 1: Dashboard

Purpose: Run overview at a glance. The operator's landing screen when launching the TUI.

```
┌──────────────────────────────────────────────────────────────┐
│  Pulse Bar: ▁▂▃▅▇█▇▅▃▂▁   Run: r-001   Ch 12/50   █ PASS 2 │
├──────────┬───────────────────────────────────────────────────┤
│          │  RESemantica — Run Overview                        │
│  ▸ Ch 12 │                                                   │
│  ■ Ch 11 │  Run         r-001                                │
│  ■ Ch 10 │  Release     rel-2026-04-23                       │
│  ■ Ch 9  │  Status      TRANSLATING                         │
│  ■ Ch 8  │  Started     14:32:07                            │
│  ■ Ch 7  │  Elapsed     0:23:41                             │
│  ...     │                                                   │
│          │  Phase Progress                                   │
│          │  Preprocess ████████████████████ 100%  5/5 stages │
│          │  Translation ██████░░░░░░░░░░░░  35%  12/34 ch   │
│          │  Reconstruct  ░░░░░░░░░░░░░░░░░   0%             │
│          │                                                   │
│          │  Recent Warnings                                  │
│          │  ▎ Ch 10 blk042  placeholder restored with retry  │
│          │  ▎ Ch 9  blk018  high risk — Pass 3 skipped       │
│          │  ▎ Ch 8  blk003  resegmentation triggered         │
│          │                                                   │
│          │  Quick Stats                                      │
│          │  Glossary     342 locked                          │
│          │  Idioms       89 policies                         │
│          │  Entities     127 confirmed                       │
│          │  Retries      7 total                             │
│          │  Avg risk     0.38                                │
├──────────┴───────────────────────────────────────────────────┤
│  142/350 blocks │ 3 warnings │ 0 failures │ 0:23:41  [1-7:?]│
└──────────────────────────────────────────────────────────────┘
```

### Widgets

| Widget | Data Source | Update Trigger |
|--------|------------|----------------|
| Run info block | `run_id`, `release_id`, `workflow_status`, `started_at` from run metadata | On load, on `stage_started`/`stage_completed` events |
| Phase progress bars | Stage completion from checkpoint metadata | On `stage_completed`, `chapter_completed` events |
| Recent warnings list | Last 5 events with severity `warning` or higher from event stream | On `warning_emitted`, `validation_failed` events |
| Quick stats | Aggregate queries: glossary count, idiom count, entity count, retry count, avg risk | On load, periodic refresh (30s) |

### Behaviors

- Selecting a warning row and pressing `Enter` navigates to Screen 4 (Warnings) filtered to that chapter.
- Phase progress bars are colored: completed sections in `green`, in-progress in `cyan`, not-started in `comment`.

---

## Screen 2: Preprocessing

Purpose: Show progress of each preprocessing stage and its sub-steps.

```
┌──────────────────────────────────────────────────────────────┐
│  Pulse Bar: ▁▂▃▅▇█▇▅▃▂▁   Run: r-001   Ch --/--   PREPROCESS│
├──────────┬───────────────────────────────────────────────────┤
│          │  Preprocessing Stages                             │
│  ■ Ch 34 │                                                   │
│  ■ Ch 33 │  EPUB Extract    ████████████████████  DONE       │
│  ...     │  Glossary        ████████████████████  DONE       │
│          │    candidates     542 discovered                   │
│          │    locked         342 promoted                     │
│          │    conflicts      3 recorded                       │
│          │  Summaries       ████████████████████  DONE       │
│          │    zh_structured  34/34 chapters                   │
│          │    zh_short       34/34 chapters                   │
│          │    en_derived     34/34 chapters                   │
│          │  Idioms          ████████████████████  DONE       │
│          │    detected       132 candidates                   │
│          │    approved       89 policies                      │
│          │  Graph MVP       ████████████████░░░  83%         │
│          │    entities       127 confirmed                    │
│          │    relationships  89 confirmed                     │
│          │    aliases        45 resolved                      │
│          │  Packets         ░░░░░░░░░░░░░░░░░░░  PENDING     │
│          │                                                   │
├──────────┴───────────────────────────────────────────────────┤
│  -- blocks │ 0 warnings │ 0 failures │ 0:05:12  [1-7:?]     │
└──────────────────────────────────────────────────────────────┘
```

### Widgets

| Widget | Data Source | Update Trigger |
|--------|------------|----------------|
| Stage rows | Checkpoint metadata per stage | On `stage_started`, `stage_completed` events |
| Sub-metrics | Aggregate counts from SQLite repos (candidates, locked, conflicts, etc.) | On stage completion for that stage |
| Progress bars | Stage completion percentage derived from checkpoint state | On stage transition events |

### Behaviors

- Each stage row expands to show sub-metrics when selected.
- Status labels: `DONE` in `green`, `RUNNING` in `cyan`, `PENDING` in `comment`, `FAILED` in `red`.
- Chapter spine is dimmed (`comment`) during preprocessing since chapter-level progress is not the primary concern.

---

## Screen 3: Translation

Purpose: Detailed per-block translation progress for the selected chapter.

```
┌──────────────────────────────────────────────────────────────┐
│  Pulse Bar: ▁▂▃▅▇█▇▅▃▂▁   Run: r-001   Ch 12/34   █ PASS 2 │
├──────────┬───────────────────────────────────────────────────┤
│          │  Chapter 12 Translation                           │
│  ■ Ch 14 │                                                   │
│  ■ Ch 13 │  Source: ch012                                    │
│  ▸ Ch 12 │  Blocks: 28/42                                   │
│  ■ Ch 11 │  Current: blk028 (PASS 2)                        │
│  ■ Ch 10 │                                                   │
│  ...     │  Block Progress                                   │
│          │  blk001  ■  ■  ■     done    risk: 0.21 LOW      │
│          │  blk002  ■  ■  ■     done    risk: 0.15 LOW      │
│          │  blk003  ■  ■  ■     done    risk: 0.82 HIGH →   │
│          │  ...                                               │
│          │  blk026  ■  ■  ■     done    risk: 0.44 MED      │
│          │  blk027  ■  ■       done    risk: 0.31 MED      │
│          │  blk028  ■  ▸               risk: 0.55 MED      │
│          │  blk029  □  □  □     pending                      │
│          │  ...                                               │
│          │                                                   │
│          │  ■ = pass complete  ▸ = in progress  □ = pending │
│          │  → = Pass 3 skipped (high risk)                   │
├──────────┴───────────────────────────────────────────────────┤
│  28/42 blocks │ 1 warning │ 0 failures │ 0:04:18  [1-7:?]  │
└──────────────────────────────────────────────────────────────┘
```

### Widgets

| Widget | Data Source | Update Trigger |
|--------|------------|----------------|
| Chapter header | Chapter source metadata, block count | On chapter load |
| Block progress list | Per-block checkpoint state, risk scores | On `paragraph_retry`, `validation_failed`, checkpoint events |
| Pass indicators | Pass completion per block | On checkpoint updates |

### Behaviors

- Each block row shows three pass indicators (P1, P2, P3).
- Selecting a block and pressing `Enter` opens a detail overlay showing:
  - Source text excerpt (first 200 chars)
  - Pass 1 output excerpt
  - Pass 2 output excerpt (if available)
  - Risk score breakdown (sub-scores)
  - Validation flags
- Block rows are color-coded by risk: `green` for LOW, `yellow` for MEDIUM, `orange` for HIGH.
- The `→` indicator means Pass 3 was skipped due to high risk.

---

## Screen 4: Warnings

Purpose: Filterable list of all warnings and failures for the current run.

```
┌──────────────────────────────────────────────────────────────┐
│  Pulse Bar: ▁▂▃▅▇█▇▅▃▂▁   Run: r-001   Ch 12/34   █ PASS 2 │
├──────────┬───────────────────────────────────────────────────┤
│          │  Warnings & Failures         [Filter: ALL ▾]      │
│  ▸ Ch 12 │                                                   │
│  ■ Ch 11 │  ▎ SEVERITY  CHAPTER  BLOCK    TYPE             │
│  ■ Ch 10 │  ─────────────────────────────────────────────── │
│  ...     │  ▎ WARNING   Ch 10    blk042   placeholder_retry │
│          │  ▎ WARNING   Ch 9     blk018   risk_skip_pass3   │
│          │  ▎ WARNING   Ch 8     blk003   resegmentation    │
│          │  ▎ WARNING   Ch 7     blk015   glossary_conflict │
│          │  ▎ INFO      Ch 5     blk022   term_corrected    │
│          │  ▎ INFO      Ch 3     blk008   ambiguity_flag    │
│          │                                                   │
│          │  Detail: Ch 10 blk042                             │
│          │  Type:         placeholder_retry                  │
│          │  Severity:     WARNING                            │
│          │  Message:      Placeholder ⟦B_2⟧ restored after   │
│          │                Pass 1 retry on resegmented block  │
│          │  Retry count: 1                                   │
│          │  Resolved:     YES                                │
│          │                                                   │
├──────────┴───────────────────────────────────────────────────┤
│  142/350 blocks │ 6 warnings │ 0 failures │ 0:23:41  [1-7:?]│
└──────────────────────────────────────────────────────────────┘
```

### Widgets

| Widget | Data Source | Update Trigger |
|--------|------------|----------------|
| Warning list | Event stream filtered by severity `warning` and above | On `warning_emitted`, `validation_failed` events |
| Filter control | Severity enum: ALL, INFO, WARNING, SERIOUS, FAILURE | Operator action |
| Detail panel | Event payload for selected warning | On row selection |

### Behaviors

- Filter toggles via `f` key, cycling through severity levels.
- Severity indicators: `INFO` in `comment`, `WARNING` in `orange`, `SERIOUS` in `yellow`, `FAILURE` in `red`.
- Selecting a row shows the full event payload in the detail panel below.
- Pressing `Enter` on a row navigates to the Translation screen for that chapter/block if applicable.

---

## Screen 5: Artifacts

Purpose: Browse the file tree of run artifacts and inspect content.

```
┌──────────────────────────────────────────────────────────────┐
│  Pulse Bar: ▁▂▃▅▇█▇▅▃▂▁   Run: r-001   Ch 12/34   █ PASS 2 │
├──────────┬───────────────────────────────────────────────────┤
│          │  Artifacts                                        │
│  ▸ Ch 12 │                                                   │
│  ■ Ch 11 │  releases/rel-2026-04-23/                         │
│  ...     │    extracted/                                      │
│          │      ch001.json                                    │
│          │      ch002.json                                    │
│          │      ...                                           │
│          │    glossary/                                       │
│          │      candidates.json                               │
│          │      locked.json                                   │
│          │    summaries/                                      │
│          │      ch001_summary_zh.json                         │
│          │      ...                                           │
│          │    packets/                                        │
│          │      ch001_packet.json                             │
│          │      ...                                           │
│          │    runs/r-001/                                     │
│          │      translation/                                  │
│          │        ch012/                                      │
│          │          pass1_blk028.txt                          │
│          │          pass2_blk028.txt                          │
│          │      validation/                                   │
│          │        ch012_validation.json                       │
│          │      events/                                       │
│          │        events.jsonl                                │
│          │                                                   │
│          │  ─── Preview: pass2_blk028.txt ───                 │
│          │  The elder stroked his beard, his gaze settling... │
│          │  "You have traversed the Azure Cloud Path," he... │
│          │                                                   │
├──────────┴───────────────────────────────────────────────────┤
│  142/350 blocks │ 3 warnings │ 0 failures │ 0:23:41  [1-7:?]│
└──────────────────────────────────────────────────────────────┘
```

### Widgets

| Widget | Data Source | Update Trigger |
|--------|------------|----------------|
| File tree | `artifacts/` directory listing | On load, on `artifact_written` events |
| Preview pane | File content (text files), JSON pretty-print (json files) | On file selection |

### Behaviors

- Directory tree is collapsible. Directories shown with `/` suffix.
- Selecting a text file shows a preview in the bottom half of the content area (last 10 lines).
- Selecting a JSON file pretty-prints it with syntax coloring: keys in `blue`, string values in `green`, numbers in `purple`.
- Pressing `Enter` on a file opens a full-screen scrollable viewer.
- Pressing `Esc` returns to the tree.

---

## Screen 6: Cleanup

Purpose: Preview and execute scoped cleanup operations.

```
┌──────────────────────────────────────────────────────────────┐
│  Pulse Bar: ▁▂▂▂▂▂▂▂▂▂▂▂▂   Run: r-001   Ch --/--   IDLE   │
├──────────┬───────────────────────────────────────────────────┤
│          │  Cleanup Workflow                                 │
│  ■ Ch 34 │                                                   │
│  ...     │  Scope:  [run]  translation  preprocess  cache    │
│          │          all                                       │
│          │                                                   │
│          │  Run ID:  r-001  (optional, for run scope)        │
│          │                                                   │
│          │  ─── Dry Run Preview ───                          │
│          │                                                   │
│          │  WILL DELETE                                      │
│          │    runs/r-001/translation/     (47 files)         │
│          │    runs/r-001/validation/      (12 files)         │
│          │    runs/r-001/events/          (1 file)           │
│          │    SQLite: 142 translation rows                   │
│          │    SQLite: 47 checkpoint rows                     │
│          │    SQLite: 89 event rows                          │
│          │                                                   │
│          │  WILL PRESERVE                                    │
│          │    releases/                      (all)            │
│          │    glossary tables                                 │
│          │    summary tables                                  │
│          │    idiom tables                                    │
│          │    config, prompts, manual overrides               │
│          │                                                   │
│          │  [d] Dry Run   [a] Apply   [Esc] Cancel           │
│          │                                                   │
├──────────┴───────────────────────────────────────────────────┤
│  -- blocks │ 0 warnings │ 0 failures │ --:--:--  [1-7:?]    │
└──────────────────────────────────────────────────────────────┘
```

### Widgets

| Widget | Data Source | Update Trigger |
|--------|------------|----------------|
| Scope selector | Cleanup scope enum: `run`, `translation`, `preprocess`, `cache`, `all` | Operator action |
| Run ID input | Free text | Operator action |
| Dry run preview | `orchestration.cleanup.plan_cleanup()` result | On `d` keypress |
| Apply confirmation | `orchestration.cleanup.apply_cleanup()` result | On `a` keypress after dry run |

### Behaviors

- Scope options are presented as toggle buttons; one must be selected.
- Pressing `d` runs `plan_cleanup()` with the selected scope and displays results.
- `a` is disabled until a dry run has been completed. After dry run, pressing `a` prompts a confirmation dialog: "Apply cleanup? This will delete N items. [y/N]".
- `WILL DELETE` items are listed in `orange`.
- `WILL PRESERVE` items are listed in `green`.
- After apply, a summary report is shown.

---

## Screen 7: Settings

Purpose: Display current configuration, model info, and budget values. Read-only view.

```
┌──────────────────────────────────────────────────────────────┐
│  Pulse Bar: ▁▂▂▂▂▂▂▂▂▂▂▂▂   Run: r-001   Ch --/--   IDLE   │
├──────────┬───────────────────────────────────────────────────┤
│          │  Configuration                                    │
│  ■ Ch 34 │                                                   │
│  ...     │  Models                                           │
│          │    translator    HY-MT1.5-7B                      │
│          │    analyst       Qwen3.5-9B-GLM5.1                │
│          │    embedding     bge-M3                           │
│          │                                                   │
│          │  LLM                                              │
│          │    base_url      http://localhost:8080             │
│          │    timeout       300s                             │
│          │    max_retries   2                                │
│          │    context_win   65536                            │
│          │                                                   │
│          │  Budget                                           │
│          │    ctx_per_pass  49152  (75% of window)           │
│          │    max_para      2000 chars                       │
│          │    max_bundle    4096 bytes                       │
│          │    risk_thresh   0.7                              │
│          │    pass3_default ON                               │
│          │                                                   │
│          │  Paths                                            │
│          │    artifact_root artifacts/                       │
│          │    db_file       resemantica.db                   │
│          │    graph_db      graph.ladybug                    │
│          │    mlflow_db     mlflow.db                        │
│          │                                                   │
│          │  Config hash: a3f2c9e1                           │
│          │                                                   │
├──────────┴───────────────────────────────────────────────────┤
│  -- blocks │ 0 warnings │ 0 failures │ --:--:--  [1-7:?]    │
└──────────────────────────────────────────────────────────────┘
```

### Widgets

| Widget | Data Source | Update Trigger |
|--------|------------|----------------|
| Config display | `settings.load_config()` result | On load |
| Config hash | Computed from config values | On load |

### Behaviors

- Read-only. No editing from the TUI.
- Values are grouped by config section and rendered as key-value pairs.
- Config hash is displayed for reference when comparing runs.

---

## Global Keybindings

| Key | Context | Action |
|-----|---------|--------|
| `1` | Any | Switch to Dashboard |
| `2` | Any | Switch to Preprocessing |
| `3` | Any | Switch to Translation |
| `4` | Any | Switch to Warnings |
| `5` | Any | Switch to Artifacts |
| `6` | Any | Switch to Cleanup |
| `7` | Any | Switch to Settings |
| `↑` / `↓` | Lists, spine | Navigate up/down |
| `Enter` | List items | Drill into selected item |
| `Esc` | Detail/overlay | Close detail, return to list |
| `r` | Dashboard, Translation | Resume run (from current checkpoint) |
| `f` | Warnings | Cycle severity filter |
| `d` | Cleanup | Run dry-run preview |
| `a` | Cleanup | Apply cleanup (after dry run) |
| `?` | Any | Show keybinding help overlay |
| `q` | Any | Quit (with confirmation if run active) |

---

## Event-to-Widget Mapping

Orchestration events drive TUI updates. Each event type maps to specific widget mutations:

| Event Type | Affected Widgets |
|------------|-----------------|
| `stage_started` | Preprocessing: stage row status → `RUNNING`. Header: pass indicator. Pulse bar: activates. |
| `stage_completed` | Preprocessing: stage row status → `DONE`, sub-metrics refresh. Dashboard: phase progress bar. |
| `chapter_started` | Header: chapter counter. Spine: chapter status → `▸`. Translation: block list loads. |
| `chapter_completed` | Spine: chapter status → `■`. Dashboard: phase progress bar. Footer: block count. |
| `paragraph_retry` | Translation: block row status update. Footer: warning count increments. |
| `packet_assembled` | Preprocessing: packet stage progress. |
| `validation_failed` | Warnings: new row appended. Footer: warning count increments. |
| `cleanup_candidate_detected` | Cleanup: preview list update. |
| `artifact_written` | Artifacts: file tree refresh for affected directory. |
| `warning_emitted` | Warnings: new row appended. Dashboard: recent warnings list. Footer: warning count. |
| `run_finalized` | Dashboard: status → `COMPLETED`. Header: pass indicator → `IDLE`. Pulse bar: deactivates. |

All event updates arrive through the shared event bus from `orchestration.events`. The TUI subscribes as a consumer and never emits events itself.

---

## Textual CSS Convention

Colors are defined as CSS custom properties in a Textual stylesheet file (`tui/palenight.tcss`):

```css
:root {
    --bg: #292D3E;
    --bg-darker: #1E1F2B;
    --bg-lighter: #34324A;
    --fg: #D4D5F0;
    --fg-bright: #EEFFFF;
    --comment: #676E95;
    --red: #FF5370;
    --orange: #F78C6C;
    --yellow: #FFCB6B;
    --green: #C3E88D;
    --cyan: #89DDFF;
    --blue: #82AAFF;
    --purple: #C792EA;
    --magenta: #BB80B3;
}
```

Widget classes use these tokens:

```css
.status-complete { color: var(--green); }
.status-active   { color: var(--cyan); }
.status-failed   { color: var(--red); }
.status-warning  { color: var(--orange); }
.status-pending  { color: var(--comment); }

.spine           { background: var(--bg-darker); }
.spine:focus     { background: var(--bg-lighter); color: var(--blue); }

.header-bar      { background: var(--bg-darker); color: var(--fg); }
.footer-bar      { background: var(--bg-darker); color: var(--fg); }
```

---

## Differentiation Callout

This TUI avoids generic dashboard patterns by:

1. **The pulse bar** — a live sparkline in the header that communicates system health without reading any text. Most TUI dashboards use static progress bars. The pulse bar makes the interface feel alive.
2. **The chapter spine** — a persistent left-column navigation that treats chapters as a book's table of contents rather than a data table. Most pipeline UIs use flat tables; the spine gives the operator a sense of position within the manuscript.
3. **Palenight color system** — a curated dark palette with intentional semantic mapping rather than default terminal colors. Every color is assigned by meaning (authority = green, working = yellow, failure = red), not by decoration.

The TUI is a **presentation layer only**. It subscribes to the orchestration event stream and reads run metadata. It never implements workflow logic, never writes to authority state, and never bypasses orchestration services. This separation is enforced by the architecture rule in `lld-12-cli-and-tui.md`.
