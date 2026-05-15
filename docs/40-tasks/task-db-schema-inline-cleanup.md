# Task: SQLite Inline Schema Cleanup

## Milestone And Depends On

- Milestone: maintenance cleanup
- Depends on: Task 31 absorb DB migrations

## Goal

Make the current SQLite schema standard explicit: active code uses inline idempotent schema creation only.

## Scope

In:

- Remove migration-compatibility leftovers from `src/resemantica/db/sqlite.py`.
- Keep `ensure_schema(conn, name)` as the public repository entrypoint.
- Update active schema documentation and repo map entries.
- Add tests that verify fresh schema creation and prevent migration-runner patterns from returning to active source.

Out:

- Changing table shapes, constraints, or repository behavior.
- Adding production database upgrade support.
- Rewriting historical task and LLD records that describe earlier migration work.

## Owned Files Or Modules

- `src/resemantica/db/sqlite.py`
- `tests/db/test_sqlite_schema.py`
- `docs/20-lld/lld-00-db-foundation.md`
- `docs/20-lld/lld-db-schema-inline-cleanup.md`
- `docs/30-operations/repo-map.md`

## Interfaces To Satisfy

- `open_connection(db_path)` behavior is unchanged.
- `ensure_schema(conn, name)` signature is unchanged and delegates to `ensure_full_schema(conn)`.
- `ensure_full_schema(conn)` creates all application tables and indexes for a fresh SQLite database.

## Tests Or Smoke Checks

- `uv run --extra dev pytest tests/db tests/translation/test_checkpoints.py tests/epub/test_roundtrip.py -q`
- `uv run --extra dev pytest tests -q`
- `uv run --extra dev ruff check src/resemantica tests docs/20-lld docs/30-operations docs/40-tasks`
- `uv run --extra dev mypy src/resemantica`
- `git diff --check`

## Done Criteria

- Active SQLite code contains no migration runner, migration tracking table cleanup, or runtime `ALTER TABLE` compatibility blocks.
- Active docs describe `db/sqlite.py` as the schema source of truth.
- Schema tests pass and enforce the standard.
