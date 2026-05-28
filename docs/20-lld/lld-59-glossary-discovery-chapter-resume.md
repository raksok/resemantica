# LLD 59: Glossary Discovery Chapter Resume

## Summary

Glossary discovery resumes at chapter extraction granularity. Reruns with the same `release_id` and `run_id` reuse completed per-chapter raw candidate state when the chapter source, summary seed content, and discovery settings still match. Stale or missing chapters are rebuilt, then corpus scoring, filtering, LLM evaluation, and deduplication continue from the rebuilt aggregate.

## Storage

`glossary_discovery_chapter_state` records one row per discovery run chapter:

- `release_id`, `run_id`, `chapter_number`
- `chapter_source_hash`
- strict `input_hash`
- `status` (`completed` or `skipped`)
- optional `skip_reason`
- `raw_candidates_json`
- `candidate_count`
- `updated_at`

Raw candidates are serialized as JSON with sorted `strategies` so state hashes and diffs remain deterministic.

`glossary_checkpoints.input_hash` stores the phase input hash for `filtered`, `eval_completed`, and `dedup_completed`. A checkpoint with a stale hash is ignored.

## Resume Behavior

Default CLI behavior is resume. `--force` clears chapter discovery state, phase checkpoints, candidates, and alias clusters for the current run before rebuilding.

On normal resume:

1. Valid phase checkpoints can skip completed phases.
2. If the discovery/filter checkpoint is missing or stale, chapter state is checked per chapter.
3. Completed chapter raws are reused.
4. Stale/missing chapter raws are regenerated and committed immediately.
5. Non-story and empty chapters are stored as skipped state and reused on later reruns.
6. Corpus statistics, scoring, deterministic filtering, LLM evaluation, and dedup are recomputed from the current durable chapter raws.

## Later Phases

LLM evaluation persists each completed batch, including cache hits and fallback reject batches. Rejected rows are durably marked `llm_rejected`, so resume evaluates only candidates still missing LLM fields.

Dedup remains a phase checkpoint. If interrupted, dedup reruns. Before writing new clusters, stale alias clusters for the same discovery run are cleared.

## Cleanup

Broad cleanup scopes remove `glossary_discovery_chapter_state` with the rest of preprocess state. This prevents stale chapter raws from surviving run, preprocess, keep-extracted, or full release cleanup.
