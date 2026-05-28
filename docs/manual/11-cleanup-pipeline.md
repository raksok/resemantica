# 11. Cleanup Pipeline

The cleanup system uses a **two-phase design** for safety: `cleanup-plan` (preview) → `cleanup-apply` (execute).

## Two-Phase Workflow

### Phase 1: Plan

```bash
uv run rsem run cleanup-plan -r <release> -R <run> -S <scope>
```

- Enumerates deletable artifacts (files + SQLite rows) without removing anything.
- Writes a plan to `<release_root>/cleanup_plan.json` (or `{artifact_root}/factory_cleanup_plan.json` for factory scope).
- Plan includes schema version `"1.2"`, artifact paths, SQLite targets, and estimated byte size.

### Phase 2: Apply

```bash
uv run rsem run cleanup-apply -r <release> -R <run> -S <scope>
```

- Reads the plan JSON and validates it before executing.
- Deletes files, removes SQLite rows, and writes a cleanup report.
- Errors are collected but do not abort the entire operation.

## Cleanup Scopes

| Scope | Deletes on Disk | Deletes in SQLite | Notes |
|-------|----------------|-------------------|-------|
| `run` | `runs/{run_id}/` | Run, extraction, translation, and preprocess rows in `resemantica.db` + 2 in `tracking.db` | Current run artifacts |
| `translation` | `runs/{run_id}/translation/` | `translation_checkpoints`, `chunk_checkpoints` (translate-range) | Translation outputs only |
| `preprocess` | `extracted/`, `summaries/`, `glossary/`, `idioms/`, `graph/`, `packets/` | Extraction, preprocess downstream, and generic run rows | All preprocessing artifacts |
| `cache` | `.cache/` | None | LLM cache only |
| `keep-extracted` | Everything except `extracted/` | Translation, preprocess downstream, and generic run rows + 2 tracking tables | Preserve extraction, remove rest |
| `last-good-chunk` | Per-chapter artifacts after last completed chunk | Chapter rows, chunk rows; rewinds checkpoints | Granular rollback |
| `all` | Everything under `release_root/` except `tracking.db`, `resemantica.db`, `graph.ladybug`, `cleanup_plan.json`, `cleanup_report.json` | Same as `run` | Full release cleanup |
| `factory` | `{artifact_root}/releases/`, `{artifact_root}/resemantica.db`, `{artifact_root}/graph.ladybug` | None | Complete reset |

## The `last-good-chunk` Scope

The most granular scope. It rewinds to the last completed chunk checkpoint:

### For `preprocess-summaries`:
- Deletes summary JSONs and packet dirs for chapters **after** the last good chapter.
- Deletes SQLite rows (`summary_drafts`, `validated_summaries_zh`, `derived_summaries_en`, `packet_metadata`) for chapters after the boundary.
- **Rewinds** `summary_checkpoints`: sets `zh_last_chapter`, `story_last_chapter`, `en_last_chapter` to `MIN(current, last_good_chapter)`.

### For `translate-range`:
- Deletes translation artifacts for chapters after the last good chapter.
- Deletes `translation_checkpoints` rows for chapters after the boundary.
- **Rewinds** `run_state` in `tracking.db`: filters `pass1_completed`, `pass2_completed`, `pass3_completed`, and `completed_chapters` lists to values ≤ `last_good_chapter`.

### Stage Resolution
- If `--stage` is provided: must be `preprocess-summaries` or `translate-range`.
- If not provided: auto-detected from the current `run_state` in `tracking.db`.

## Safety & Validation

### Plan Validation (`_validate_plan`)

Before executing, the plan is checked against:

| Check | What It Verifies |
|-------|-----------------|
| Schema version | Must match `"1.2"` (prevents stale plans) |
| Scope validity | Must be a known scope |
| Scope mismatch | Plan scope must match requested scope (bypassed with `--force`) |
| Release ID | Plan release must match requested release |
| Run ID | Plan run must match requested run |
| Root path | All artifact paths must be under the expected root |
| Artifact containment | Every path must be under `expected_root` (prevents path-traversal) |
| SQLite whitelist | Target set must exactly match what `_sqlite_targets_for_scope()` returns |

### Protected Artifacts

The `all` scope preserves 5 artifacts:
- `tracking.db`
- `resemantica.db`
- `graph.ladybug`
- `cleanup_plan.json`
- `cleanup_report.json`

### Force Flag

| Scenario | `--force` off | `--force` on |
|----------|---------------|--------------|
| Scope mismatch | Aborts | Allows (except `factory`) |
| Release/run ID mismatch | Aborts | Still aborts |
| Factory scope mismatch | Aborts | Still aborts |

## SQLite Cleanup Per Scope

| Scope | `tracking.db` Tables | `resemantica.db` Tables |
|-------|---------------------|------------------------|
| `run` | `events`, `run_state` | `translation_checkpoints`, `chunk_checkpoints` (translate-range), `extracted_chapters`, `extracted_blocks`, `summary_checkpoints`, `summary_drafts`, `validated_summaries_zh`, `derived_summaries_en`, `glossary_checkpoints`, `glossary_discovery_chapter_state`, `glossary_translation_votes`, `glossary_alias_clusters`, `glossary_candidates`, `idiom_checkpoints`, `idiom_translation_votes`, `idiom_candidates`, `graph_extraction_drafts`, `packet_metadata`, `checkpoints`, `runs` |
| `translation` | — | `translation_checkpoints`, `chunk_checkpoints` (translate-range) |
| `preprocess` | — | Extraction rows + preprocess downstream rows, including `glossary_discovery_chapter_state`, + `checkpoints`, `runs` |
| `keep-extracted` | `events`, `run_state` | Translation rows + preprocess downstream rows, including `glossary_discovery_chapter_state`, + `checkpoints`, `runs` |
| `all` | `events`, `run_state` | Same as `run` |
| `last-good-chunk` | Rewinds `run_state` | Deletes chapter rows (4 tables) + chunk rows; rewinds `summary_checkpoints` |
| `cache` / `factory` | — | — |

## Common Cleanup Workflows

```bash
uv run rsem run cleanup-plan -r v1.0 -R run1 -S translation
```
```bash
uv run rsem run cleanup-apply -r v1.0 -R run1 -S translation
```
```bash
uv run rsem run cleanup-plan -r v1.0 -R run1 -S all
```
```bash
uv run rsem run cleanup-apply -r v1.0 -R run1 -S all
```
```bash
uv run rsem run cleanup-plan -r v1.0 -R run1 -S factory
```
```bash
uv run rsem run cleanup-apply -r v1.0 -R run1 -S factory -f
```
```bash
uv run rsem run cleanup-plan -r v1.0 -R run1 -S last-good-chunk --stage preprocess-summaries
```
```bash
uv run rsem run cleanup-apply -r v1.0 -R run1 -S last-good-chunk --stage preprocess-summaries
```
