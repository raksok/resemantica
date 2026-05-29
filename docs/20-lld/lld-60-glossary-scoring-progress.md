# LLD 60: Glossary Scoring Progress

## Summary

Glossary discovery now reports progress during the corpus scoring phase and emits finalization events after alias clustering. This is a visibility-only change: candidate generation, scoring math, filtering thresholds, checkpoints, and output artifacts are unchanged.

## Events

After chapter discovery and before deterministic filtering, discovery emits:

- `preprocess-glossary.discover.scoring.started`
- `preprocess-glossary.discover.scoring.progress`
- `preprocess-glossary.discover.scoring.completed`

The started event includes `candidate_count`, `total_chapters`, and `phase="scoring"`.

Progress events use the generic payload shape:

- `phase`: `c_value` or `composite`
- `processed_count`
- `total_count`
- `percent`

The completed event includes `candidate_count`, `duration_ms`, `top_score`, `median_score`, and `min_score`.

After deterministic filtering and LLM evaluation, discovery emits finalization events for the dedup/checkpoint/snapshot boundary:

- `preprocess-glossary.discover.dedup.started`
- `preprocess-glossary.discover.dedup.completed`
- `preprocess-glossary.discover.dedup.persisted`
- `preprocess-glossary.discover.checkpoint.completed`
- `preprocess-glossary.discover.snapshot.artifact_written`

The dedup events include `candidate_count`, `cluster_count`, `alias_merged_count`, and `skipped`/`reason` when the phase is skipped because no candidates remain or a valid `dedup_completed` checkpoint is reused.

The persistence event includes `cluster_count`, `candidate_count`, and `alias_merged_count`. The checkpoint event includes `checkpoint_stage="dedup_completed"` and the dedup input hash. The snapshot event includes `artifact_path` and `candidate_count`.

Ordering is deterministic:

1. `dedup.started`
2. `dedup.completed`
3. `dedup.persisted`
4. `checkpoint.completed`
5. `snapshot.artifact_written`
6. `discover.completed`

## Cadence

The scorer reports progress every `max(100, total_count // 100)` candidates and always emits a final update for each phase. Small candidate sets therefore still produce a visible final progress event.

## Consumers

CLI progress and TUI stage progress treat any event ending in `.progress` as a progress task keyed by `event_type.removesuffix(".progress")`. Reduced event persistence samples `.progress` events using the existing progress sampling policy, so large candidate sets do not flood the tracking database.
