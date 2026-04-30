# Task 17: Data Storage & Contracts

## Goal

Ensure all storage layers comply with the `DATA_CONTRACT.md`, specifically regarding graph-native queries, extraction metadata, and comprehensive cleanup.

## Scope

In:

- Refactoring `src/resemantica/graph/client.py` to move from sidecar JSON files to graph-native queries in LadybugDB for filtering and retrieval.
- Updating the extraction stage to record chapter and block metadata in SQLite (currently only on filesystem).
- Fixing the cleanup logic in `src/resemantica/orchestration/cleanup.py` to remove release-specific rows from the global `resemantica.db`.
- Ensuring all durable records carry the required metadata (`schema_version`, `run_id`, etc.) as defined in `DATA_CONTRACT.md`.

Out:

- Changing the underlying database engines (SQLite/LadybugDB).
- Modifying the graph extraction LLM logic (Task 14a already covers this).

## Owned Files Or Modules

- `src/resemantica/graph/client.py`
- `src/resemantica/db/sqlite.py`
- `src/resemantica/orchestration/cleanup.py`
- `src/resemantica/epub/extractor.py`

## Interfaces To Satisfy

- `LadybugGraphBackend.get_chapter_safe_subgraph()`
- `ExtractionRepo.record_extraction_metadata()`
- `OrchestrationRunner.run_stage("reset", ...)`

## Tests Or Smoke Checks

- Run a preprocessing run and verify that `resemantica.db` contains the extraction metadata.
- Perform a scoped cleanup and verify that all related rows are removed from both `tracking.db` and `resemantica.db`.
- Verify that chapter-safe graph retrieval results match the expected output without relying on sidecar JSON.

## Done Criteria

- LadybugDB is the authority for graph state, using graph-native queries.
- Extraction metadata is persisted in SQLite according to the data contract.
- Cleanup is comprehensive across all databases.
- All records comply with the global metadata requirements in `DATA_CONTRACT.md`.
