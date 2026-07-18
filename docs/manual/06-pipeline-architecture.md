# 6. Pipeline Architecture

## Milestone Order

The system was built across 14 milestones (M1–M14). Each milestone maps to a task brief in `docs/40-tasks/`:

| MS | Task | Description |
|----|------|-------------|
| M1 | task-01 | EPUB round-trip extraction and reconstruction |
| M2 | task-02 | Single-chapter translation (Pass 1 + Pass 2) |
| M3 | task-03 | Canonical glossary system |
| M4 | task-04 | Summary memory system |
| M5 | task-05 | Idiom workflow |
| M6 | task-06 | Graph MVP (LadybugDB) |
| M7 | task-07 | Lightweight world model |
| M8 | task-08 | Chapter packets with graph integration |
| M9 | task-09 | Pass 3 + risk handling |
| M10 | task-10 | Orchestration + production workflow |
| M11 | task-11 | Cleanup workflow |
| M12 | task-12 | CLI + TUI |
| M13 | task-13 | Observability + evaluation |
| M14 | task-14 | Batch pilot + final rebuild |

## Production Stage Order

The canonical stage order is defined in `STAGE_ORDER` (`orchestration/models.py`):

```text
preprocess-summaries
    ↓
preprocess-glossary
    ↓
preprocess-idioms
    ↓
preprocess-graph
    ↓
preprocess-continuity
    ↓
packets-build
    ↓
translate-range
    ↓
epub-rebuild
```

Each stage reads from SQLite/LadybugDB/filesystem and writes its outputs before the next stage begins.

## Stage Gates & Locks

### Forward-Only Stage Transitions

Stages enforce a forward-only ordering via `legal_transition()` (`orchestration/models.py`):

- If no prior state exists, any stage is allowed.
- Re-running the **same** stage is always allowed.
- Moving **forward** in `STAGE_ORDER` is allowed.
- Moving **backward** is **denied** unless `--allow-rewind` is set.

When `uv run rsem run resume` loads a checkpoint, it checks the persisted run state:
- If the last stage is `completed`, resume skips to the **next** stage.
- If the last stage is `failed`, `stopped`, or `running`, it **re-runs** that stage.

### Per-Stage Gate Checks

Before executing, each stage in `STAGE_ORDER` runs validation gates (`orchestration/gates.py`). The gate matrix shows which checks apply:

| Stage | Extracted inputs | Unresolved votes | Summaries | Graph | Packets | Rebuild |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|
| `preprocess-summaries` | ✓ | | | | | |
| `preprocess-glossary` | ✓ | | | | | |
| `preprocess-idioms` | ✓ | ✓ | ✓ | | | |
| `preprocess-graph` | ✓ | ✓ | ✓ | | | |
| `preprocess-continuity` | ✓ | ✓ | ✓ | ✓ | | |
| `packets-build` | ✓ | ✓ | ✓ | ✓ | | |
| `translate-range` | ✓ | ✓ | ✓ | ✓ | ✓ | |
| `epub-rebuild` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

#### Gate Functions

**`_check_extracted_inputs()`** — Validates the extracted chapter manifest exists, is parseable, has correct chapter numbers, and each chapter file exists. Runs for every stage.

**`_check_unresolved_preprocess_votes()`** — Checks for glossary candidates with `resolution_status = 'pending'/'unresolved'` and empty translations, and idiom candidates with unresolved rendering votes. Blocks downstream stages with hard failures.

**`_check_summary_inputs()`** — Verifies all story chapters have approved `chapter_summary_zh_short` and `story_so_far_zh` entries in both SQLite (`validated_summaries_zh`) and filesystem (JSON artifacts). Non-story chapters are skipped.

**`_check_graph_inputs()`** — Checks the graph snapshot file exists on disk and has a corresponding row in the `graph_snapshots` SQLite table.

**`_check_packet_inputs()`** — For each story chapter, verifies `packet_metadata` exists in SQLite and both packet and bundle artifact files exist on disk. Skips chapters with known skip events (empty records, non-story).

**`_check_rebuild_inputs()`** — For each selected story chapter, verifies the placeholder map and requires an exact mapping from every extracted parent block to a non-empty final Pass 2/3 output. Non-story chapters without translation artifacts keep their original XHTML; those with artifacts must pass the same completeness audit.

### Gate Failure Handling

When a gate fails:
1. A checkpoint is saved with the current chapter range.
2. If the failure is caused by **unresolved preprocessing votes** (glossary candidates or idiom renderings), review files are automatically generated (`review.json`/`review.csv`) so the user can edit and re-run.
3. Run state is updated to `failed`.
4. A `{stage_name}.gate_failed` event is emitted.
5. The stage returns `success=False` with gate metadata.

The `--force` flag bypasses checkpoint resume but does **not** bypass gate checks.

### Text Segmentation

Before translation, each chapter's XHTML is parsed into extractable units (`epub/parser.py`):
- **Blocks**: Leaf XHTML elements (p, h1-h6, li, td, div) that are not parents of other blocks
- **Segments**: Blocks split at sentence boundaries (Chinese `。！？` and English `.!?`) with a 1500-character maximum
- **Placeholders**: Structural elements (images, links, MathML, ruby) are replaced with `⫷TYPE_N⫸` / `⫸/TYPE_N⫷` and restored during rebuild

### Chunk-Level Checkpoints

Long-running stages (summaries, translate-range) use chunk-level checkpoints (`orchestration/chunk_checkpoints.py`) for granular progress:

- Each chunk is identified by `(release_id, run_id, stage_name, chunk_index)`.
- On completion, each chunk saves status `"completed"` to the `chunk_checkpoints` table.
- On resume, `last_completed_chunk()` finds the highest completed chunk index and resumes from the next one.
- The `last-good-chunk` cleanup scope can rewind to the last completed chunk, preserving earlier work.

## Runtime Lifecycle

1. **Config loading** — TOML parsed into `AppConfig` dataclasses
2. **Path derivation** — All artifact paths computed from config + release_id
3. **Logging setup** — Loguru configured for console + file output
4. **Stage dispatch** — Command routed to handler function or `OrchestrationRunner.run_stage()`
5. **Gate check** — `check_stage_gate()` validates upstream dependencies
6. **Transition check** — `legal_transition()` enforces forward-only ordering
7. **Execution** — Stage work begins, writing durable checkpoints per chunk
8. **Event bus** — Stages emit events consumed by CLI progress bar, TUI, and tracking DB

Glossary discovery emits chapter-level progress while extracting candidates. It also emits
`preprocess-glossary.discover.scoring.started`, `.progress`, and `.completed` events during
corpus scoring, with `.progress` payloads reporting `phase`, `processed_count`,
`total_count`, and `percent`.

Graph extraction emits a resume summary before chapter work, then
`preprocess-graph.extract.progress` events while processing or reusing chapter
drafts. These progress payloads report processed/total chapters, cache hits,
skips, and extracted graph counts.

## Translation Sub-flow

For each chapter, the translation sub-stage runs:

```text
       ┌──────────────────┐
       │  ChapterPacket   │  (glossary, summaries, idioms, graph)
       └────────┬─────────┘
                ↓
       ┌──────────────────┐
       │   Pass 1  (translator)  │  → source-faithful draft
       └────────┬─────────┘
                ↓
       ┌──────────────────┐
       │   Pass 2  (analyst)    │  → fidelity correction
       └────────┬─────────┘
                ↓
       ┌──────────────────┐
       │   Pass 3  (analyst)*   │  → readability polish (*optional)
       └────────┬─────────┘
                ↓
       ┌──────────────────┐
       │  pass artifact    │  → stored for rebuild stage
       └──────────────────┘
```

Pass 3 is only applied to paragraphs flagged as high-risk by the risk classifier (score > `risk_threshold_high`), or when `pass3_default` is enabled.

Pass 1 bypasses the model for punctuation/symbol-only and placeholder-only blocks, preserving their source exactly. Empty or Chinese-bearing model output receives two English-only correction attempts. Pass 2 starts only when all extracted parent blocks have successful Pass 1 output, and cached Pass 1/2 artifacts are repaired at block granularity rather than accepted solely from checkpoint status.

## Event Bus

The orchestration layer uses an in-process event bus. Events flow to:

- **CLI progress** — `CliProgressSubscriber` for real-time terminal feedback
- **TUI** — Async event adapter pushing to Textual widgets
- **Tracking DB** — Persistent event store for post-hoc analysis

Events are classified by granularity level and can be sampled.
