# LLD 00: SQLite DB Foundation

## Summary

Define the SQLite foundation shared by authority stores, working-state repositories, checkpoints, packet metadata, and cleanup bookkeeping.

## Public Interfaces

Database file:

- `artifacts/releases/{release_id}/resemantica.db`

Python modules:

- `db.sqlite.open_connection()`
- `db.sqlite.ensure_full_schema()`
- `db.sqlite.ensure_schema(conn, name)`
- domain repository classes such as `glossary.repo.GlossaryRepository`

Schema source of truth:

- `src/resemantica/db/sqlite.py`
- `ensure_full_schema()` defines all application tables and indexes inline with idempotent `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` statements.
- `ensure_schema(conn, name)` remains the compatibility entrypoint for domain repositories and delegates to `ensure_full_schema()`.

## Data Flow

1. Resolve the database path from config, defaulting to `artifacts/releases/{release_id}/resemantica.db`.
2. Open one SQLite connection per command or workflow boundary.
3. **Execute `PRAGMA journal_mode=WAL;` on every connection immediately after opening.** This is mandatory to prevent `Database is locked` errors when the TUI (M12) reads concurrently with the orchestrator (M10).
4. Ensure the inline schema through `db.sqlite.ensure_schema(conn, name)`.
5. Pass the shared connection into per-domain repositories.
6. Use transactions for promotion, checkpoint, packet metadata, and cleanup operations.
7. Use in-memory SQLite connections for repository tests (WAL is not needed for in-memory connections).

## Validation Ownership

- `db.sqlite.ensure_full_schema()` owns schema idempotency for clean SQLite databases.
- Repository methods own domain-level constraints and should not bypass validators.
- Domain repositories must keep authority state, working state, and operational state separate.
- Schema creation failures stop startup before any workflow mutates state.

## Resume And Rerun

- Table-level `schema_version` fields and artifact hashes are recorded where domain repositories require them.
- Checkpoint and packet metadata repositories must support idempotent rereads.
- Cleanup operations must update SQLite bookkeeping in the same workflow that removes filesystem artifacts.

## Tests

- inline schema creation on a fresh SQLite database
- repository tests using in-memory SQLite
- transaction rollback on failed promotion or cleanup mutation
- configured database path resolves under `artifacts/releases/{release_id}/resemantica.db` by default
- `open_connection()` sets `journal_mode=WAL` on file-backed databases
- concurrent read and write do not produce `Database is locked`
- source guard preventing migration-runner patterns from returning to active code

## Out Of Scope

- SQLAlchemy or Alembic integration
- automatic schema generation from models
- graph storage, which belongs to LadybugDB
- production upgrade paths for existing SQLite databases
