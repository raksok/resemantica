# Task 17: Data Storage & Contracts

## Milestone And Depends On

Milestone: M17

Depends on: M15, M16

## Goal

Ensure all storage layers comply with the `DATA_CONTRACT.md`, specifically regarding graph-native queries, extraction metadata, and comprehensive cleanup.

## Scope

In:

- Refactor `src/resemantica/graph/client.py` so LadybugDB is the durable authority for graph entities, aliases, appearances, and relationships.
- Remove `.state.json` sidecar state as the graph source of truth.
- Implement graph-native filtering and retrieval, including chapter-safe subgraph access.
- Add SQLite tables and repository methods for extraction chapter/block metadata.
- Update the extraction stage to record chapter and block metadata in SQLite in addition to immutable JSON artifacts.
- Fix cleanup path derivation so it targets `artifacts/releases/{release_id}` consistently.
- Fix cleanup logic to remove release/run-specific rows from both release `tracking.db` and global `resemantica.db`.
- Persist cleanup plan/report metadata according to `DATA_CONTRACT.md`.
- Ensuring all durable records carry the required metadata (`schema_version`, `run_id`, etc.) as defined in `DATA_CONTRACT.md`.

Out:

- Changing the underlying database engines (SQLite/LadybugDB).
- Modifying the graph extraction LLM logic (Task 14a already covers this).

## Owned Files Or Modules

- `src/resemantica/graph/client.py`
- `src/resemantica/db/sqlite.py`
- `src/resemantica/orchestration/cleanup.py`
- `src/resemantica/epub/extractor.py`
- `src/resemantica/db/migrations/`
- `src/resemantica/db/extraction_repo.py` (new if useful)
- `tests/graph/`
- `tests/epub/`
- `tests/orchestration/`

## Interfaces To Satisfy

- `LadybugGraphBackend.get_chapter_safe_subgraph()`
- `ExtractionRepo.record_extraction_metadata()`
- `OrchestrationRunner.run_stage("reset", ...)`
- cleanup plan/report schemas from `DATA_CONTRACT.md`

## Tests Or Smoke Checks

- Unit test Ladybug-backed state survives process restart without reading `.state.json`.
- Unit test `get_chapter_safe_subgraph(chapter_number=N)` excludes future appearances/relationships.
- Run a preprocessing run and verify that `resemantica.db` contains the extraction metadata.
- Perform a scoped cleanup and verify that all related rows are removed from both `tracking.db` and `resemantica.db`.
- Verify that chapter-safe graph retrieval results match the expected output without relying on sidecar JSON.
- Run `uv run --with pytest pytest tests/graph tests/epub tests/orchestration -q`.

## Done Criteria

- LadybugDB is the authority for graph state, using graph-native queries.
- Extraction metadata is persisted in SQLite according to the data contract.
- Cleanup is comprehensive across all databases.
- All records comply with the global metadata requirements in `DATA_CONTRACT.md`.
- `docs/20-lld/lld-17-data-storage-contracts.md` is implemented and kept in sync.
