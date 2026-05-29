# LLD 60: Glossary Scoring Progress

## Summary

Glossary discovery now reports progress during corpus scoring and emits scoped events for filtering, evaluation, alias clustering, checkpoints, snapshots, and failures. This is a visibility-only change: candidate generation, scoring math, filtering thresholds, checkpoints, and output artifacts are unchanged.

## Events

After chapter discovery and before deterministic filtering, discovery emits:

- `preprocess-glossary.discover.prefilter.started`
- `preprocess-glossary.discover.prefilter.completed`
- `preprocess-glossary.discover.scoring.started`
- `preprocess-glossary.discover.scoring.progress`
- `preprocess-glossary.discover.scoring.completed`

The prefilter events expose the df>=2 pre-score filter with `candidate_count`, `pre_filter_count`, `kept_count`, `filtered_count`, `total_chapters`, `phase="prefilter"`, and optional skip metadata. The scoring started event includes `candidate_count`, `total_chapters`, and `phase="scoring"`.

Progress events use the generic payload shape:

- `phase`: `c_value` or `composite`
- `processed_count`
- `total_count`
- `percent`

The scoring completed event includes `candidate_count`, `duration_ms`, `top_score`, `median_score`, and `min_score`.

Deterministic filtering emits scoped events around filtering, candidate persistence, and the `filtered` checkpoint. The legacy `preprocess-glossary.discover.filter_completed` event remains for compatibility.

- `preprocess-glossary.discover.filter.started`
- `preprocess-glossary.discover.filter.completed`
- `preprocess-glossary.discover.filter.persisted`
- `preprocess-glossary.discover.checkpoint.completed` with `checkpoint_stage="filtered"`

LLM evaluation emits scoped phase and batch events, while keeping the legacy `preprocess-glossary.eval.eval_batch_*` events.

- `preprocess-glossary.discover.eval.started`
- `preprocess-glossary.discover.eval.batch_started`
- `preprocess-glossary.discover.eval.batch_completed`
- `preprocess-glossary.discover.eval.batch_cached`
- `preprocess-glossary.discover.eval.batch_failed` with severity `warning`
- `preprocess-glossary.discover.eval.completed`
- `preprocess-glossary.discover.eval.persisted`
- `preprocess-glossary.discover.checkpoint.completed` with `checkpoint_stage="eval_completed"` when that checkpoint is actually saved or reused.

After deterministic filtering and LLM evaluation, discovery emits finalization events for the dedup/checkpoint/snapshot boundary:

- `preprocess-glossary.discover.dedup.started`
- `preprocess-glossary.discover.dedup.completed`
- `preprocess-glossary.discover.dedup.persisted`
- `preprocess-glossary.discover.checkpoint.completed`
- `preprocess-glossary.discover.snapshot.artifact_written`

The dedup events include `candidate_count`, `cluster_count`, `alias_merged_count`, and `skipped`/`reason` when the phase is skipped because no candidates remain or a valid `dedup_completed` checkpoint is reused.

The persistence event includes `cluster_count`, `candidate_count`, and `alias_merged_count`. Checkpoint events include `checkpoint_stage`, the stage input hash, `candidate_count`, and `skipped`/`reason` for reused checkpoints. The snapshot event includes `artifact_path` and `candidate_count`. Discovery failures emit `preprocess-glossary.discover.failed` with severity `error`, `phase`, and `error`.

Ordering is deterministic:

1. `prefilter.started/completed`
2. `scoring.started/progress/completed`
3. `filter.started/completed/filter_completed/persisted`
4. `checkpoint.completed` for `filtered`
5. `eval.started/.../completed/persisted`
6. `checkpoint.completed` for `eval_completed` when saved or reused
7. `dedup.started/completed/persisted`
8. `checkpoint.completed` for `dedup_completed`
9. `snapshot.artifact_written`
10. `discover.completed`

## Cadence

The scorer reports progress every `max(100, total_count // 100)` candidates and always emits a final update for each phase. Small candidate sets therefore still produce a visible final progress event.

## Consumers

CLI progress and TUI stage progress treat any event ending in `.progress` as a progress task keyed by `event_type.removesuffix(".progress")`. Reduced event persistence samples `.progress` events using the existing progress sampling policy, so large candidate sets do not flood the tracking database.
