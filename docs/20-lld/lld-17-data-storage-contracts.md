# LLD 17: Data Storage And Contracts

## Summary

Task 17 brings storage behavior back into alignment with `DATA_CONTRACT.md`. The key fixes are graph-native LadybugDB authority, SQLite extraction metadata, consistent release/run cleanup, and durable metadata fields on records that affect runtime behavior.

## Public Interfaces

Python:

- `LadybugGraphBackend.get_chapter_safe_subgraph(chapter_number, include_provisional=False)`
- `ExtractionRepo.record_extraction_metadata(release_id, run_id, chapter_result)`
- `ExtractionRepo.list_chapter_blocks(release_id, chapter_number)`
- `OrchestrationRunner.run_stage("reset", scope=..., dry_run=...)`
- `plan_cleanup(release_id, run_id, scope=..., dry_run=True)`
- `apply_cleanup(release_id, run_id, scope=..., force=False)`

## SQLite Extraction Metadata

Add SQLite tables for deterministic extraction metadata. The exact physical schema may vary, but it must cover the contract fields.

Recommended tables:

- `extracted_chapters`
- `extracted_blocks`

`extracted_chapters` fields:

- `chapter_id`
- `release_id`
- `run_id`
- `chapter_number`
- `source_document_path`
- `chapter_source_hash`
- `placeholder_map_ref`
- `created_by_stage`
- `validation_status`
- `schema_version`
- `created_at`
- `updated_at`

`extracted_blocks` fields:

- `block_id`
- `chapter_id`
- `release_id`
- `run_id`
- `chapter_number`
- `segment_id`
- `parent_block_id`
- `block_order`
- `segment_order`
- `source_text_zh`
- `placeholder_map_ref`
- `chapter_source_hash`
- `schema_version`
- `created_at`
- `updated_at`

The extractor still writes immutable JSON artifacts. SQLite metadata is the structured index for query, cleanup, and reconstruction.

## LadybugDB Authority

LadybugDB must be the durable authority for graph entities, aliases, appearances, and relationships.

Required behavior:

- do not use `.state.json` as the graph source of truth
- create graph node/edge structures in LadybugDB
- upserts write to LadybugDB
- list/query methods read from LadybugDB
- snapshots may still be exported to JSON for reproducibility, but exports are artifacts, not authority

`get_chapter_safe_subgraph(chapter_number)` must return only:

- confirmed entities visible by that chapter
- aliases first seen no later than that chapter
- appearances with `chapter_number <= requested`
- relationships whose validity interval includes or precedes the requested chapter and does not reveal future state

## Cleanup Contract

Cleanup must use the same path convention as `derive_paths()`:

```text
artifacts/releases/{release_id}
```

The plan must enumerate:

- filesystem targets
- SQLite targets in global `resemantica.db`
- release `tracking.db` targets
- preserved targets

The apply step must:

- refuse to run without a matching persisted plan
- delete only targets listed in the plan unless `force` explicitly expands policy
- remove release/run-specific rows from global `resemantica.db`
- remove matching rows from release `tracking.db`, including `events` and `run_state`
- write a cleanup report with deleted/preserved targets and warnings

## Durable Metadata Requirements

Durable records that influence runtime behavior should include:

- `schema_version`
- `created_at`
- `updated_at`
- `created_by_stage`
- `run_id`
- `release_id` where applicable
- `chapter_number` where applicable
- `artifact_path` where applicable
- `source_hash` where applicable
- `validation_status` where applicable

If an existing authority table uses stage-specific names such as `approval_run_id`, do not rename it casually. Add compatibility fields only when needed and document the mapping.

## Validation Ownership

- extraction validates block ordering and placeholder map references before recording metadata
- graph client validates chapter-safe query bounds
- cleanup validates plan/apply scope matching
- orchestration validates reset stage options

## Tests

- extraction writes both JSON artifacts and SQLite metadata
- SQLite extraction rows contain required metadata
- Ladybug-backed graph state survives process restart without `.state.json`
- chapter-safe graph query excludes future relationships
- cleanup plan includes filesystem, tracking DB, and global DB targets
- cleanup apply removes scoped rows from both databases
- cleanup preserves locked authority state unless scope explicitly includes it

## Migration Notes

Current drift to fix:

- graph client touches LadybugDB but persists real state in `.state.json`
- extraction metadata is filesystem-only
- cleanup currently targets `artifacts/{release_id}` instead of `artifacts/releases/{release_id}`
- cleanup deletes only tracking events, not global DB rows or run state
