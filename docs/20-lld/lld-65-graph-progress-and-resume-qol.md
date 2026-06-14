# LLD 65: Graph Progress And Resume QoL

## Summary

`preprocess-graph` now reports chapter extraction progress, draft-resume state, and graph artifact writes without changing graph extraction semantics or prompt behavior.

The stage already persisted per-chapter extraction drafts keyed by release, run, chapter, source hash, and graph prompt version. This change makes that resume state visible and makes retry planning use the same freshness check.

## Events

Graph extraction emits:

- `preprocess-graph.extract.resume_summary`
- `preprocess-graph.extract.started`
- `preprocess-graph.extract.progress`
- `preprocess-graph.extract.completed`

The resume summary includes reusable, stale, missing, and forced rebuild draft counts. Progress events use the generic progress shape with `processed_count` and `total_count`, plus chapter metadata and graph counters such as cache hits, skipped chapters, extracted entities, relationships, and deferred terms.

Graph artifact writes emit:

- `preprocess-graph.snapshot.artifact_written`
- `preprocess-graph.warnings.artifact_written`

These events include `artifact_path`, `artifact_format`, and relevant counts.

## Retry Planning

`run retry-failed --stage preprocess-graph` treats a graph draft as fresh only when the row matches the current:

- `release_id`
- `run_id`
- `chapter_number`
- `chapter_source_hash`
- `graph_extract.txt` prompt version

Missing or stale draft rows are retryable. If drafts are fresh but the stage failed during merge or validation, retry reuses those drafts and re-runs the merge/validation boundary.

## Consumers

CLI progress uses the existing `.progress` handling for graph extraction progress and adds graph-specific log-panel formatting for resume summaries, per-chapter counts, and artifact writes. Reduced event persistence can sample `.progress` events using the existing progress sampling policy.
