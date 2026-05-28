# Task 59: Glossary Discovery Chapter Resume

## Milestone

M59

## Depends On

M58

## Goal

Make `gls-discover` resumable at chapter extraction granularity. Reruns should reuse valid per-chapter raw candidate state, rebuild only stale or missing chapters, and continue through scoring, filtering, LLM evaluation, and deduplication.

## Scope

- Add durable `glossary_discovery_chapter_state` rows keyed by release, run, and chapter.
- Store chapter source hash, strict input hash, status, skip reason, raw candidates JSON, candidate count, and update time.
- Reuse only when chapter source hash, summary seed content, and discovery settings match.
- Persist skipped non-story and empty chapters.
- Add phase checkpoint input hashes so stale `glossary_checkpoints` rows are ignored.
- Persist LLM eval batches durably, including cached and fallback reject batches.
- Clear stale alias clusters before writing current dedup results.
- Ensure zero-candidate rebuilds remove old `glossary_candidates` rows.
- Include the new table in cleanup scope planning/apply behavior.
- Document command and cleanup behavior.

## Interfaces

- CLI: unchanged. Resume remains default; `--force` rebuilds.
- Storage: new `glossary_discovery_chapter_state` table and `glossary_checkpoints.input_hash`.
- Artifacts: `candidates.json` output remains unchanged.

## Tests

- Chapter state read/write, deterministic raw candidate serialization, and strict input-hash reuse.
- Resume skips already persisted chapter extraction.
- Stale source hash re-extracts only affected chapters.
- `--force` clears stale discovery state.
- Skipped non-story and empty chapters persist and resume.
- Empty rebuild removes stale candidates.
- Evaluator persistence callback runs for normal, cached, and fallback batches.
- Cleanup scopes include `glossary_discovery_chapter_state`.

## Done Criteria

- `gls-discover` avoids repeated chapter segmentation on valid resume.
- Stale chapter or settings input does not reuse invalid raws.
- Later phases can resume from durable candidate/eval state.
- Cleanup removes the new state table rows for broad cleanup scopes.
- Focused glossary, evaluator, schema, cleanup, and lint checks pass.
