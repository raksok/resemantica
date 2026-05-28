# LLD 60: Glossary Scoring Progress

## Summary

Glossary discovery now reports progress during the corpus scoring phase. This is a visibility-only change: candidate generation, scoring math, filtering thresholds, and output artifacts are unchanged.

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

## Cadence

The scorer reports progress every `max(100, total_count // 100)` candidates and always emits a final update for each phase. Small candidate sets therefore still produce a visible final progress event.

## Consumers

CLI progress and TUI stage progress treat any event ending in `.progress` as a progress task keyed by `event_type.removesuffix(".progress")`. Reduced event persistence samples `.progress` events using the existing progress sampling policy, so large candidate sets do not flood the tracking database.
