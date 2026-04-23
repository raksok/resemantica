# LLD 00: SQLite DB Foundation

## Summary

Define the SQLite foundation shared by authority stores, working-state repositories, checkpoints, packet metadata, and cleanup bookkeeping.

## Public Interfaces

Database file:

- `artifacts/resemantica.db`

Migration files:

- `src/resemantica/db/migrations/001_initial.sql`
- later migrations use increasing numeric prefixes

Python modules:

- `db.sqlite.open_connection()`
- `db.sqlite.apply_migrations()`
- `db.sqlite.get_schema_version()`
- domain repository classes such as `glossary.repo.GlossaryRepository`

## Data Flow

1. Resolve the database path from config, defaulting to `artifacts/resemantica.db`.
2. Open one SQLite connection per command or workflow boundary.
3. **Execute `PRAGMA journal_mode=WAL;` on every connection immediately after opening.** This is mandatory to prevent `Database is locked` errors when the TUI (M12) reads concurrently with the orchestrator (M10).
4. Apply manual version-numbered migrations from `db/migrations/`.
5. Pass the shared connection into per-domain repositories.
6. Use transactions for promotion, checkpoint, packet metadata, and cleanup operations.
7. Use in-memory SQLite connections for repository tests (WAL is not needed for in-memory connections).

## Validation Ownership

- `db.sqlite.apply_migrations()` owns schema version ordering and idempotency.
- Repository methods own domain-level constraints and should not bypass validators.
- Domain repositories must keep authority state, working state, and operational state separate.
- Migration failures stop startup before any workflow mutates state.

## Resume And Rerun

- Schema version is recorded in run metadata and relevant artifact metadata.
- Checkpoint and packet metadata repositories must support idempotent rereads.
- Cleanup operations must update SQLite bookkeeping in the same workflow that removes filesystem artifacts.

## Tests

- migration ordering and schema-version recording
- repository tests using in-memory SQLite
- transaction rollback on failed promotion or cleanup mutation
- configured database path resolves to `artifacts/resemantica.db` by default
- `open_connection()` sets `journal_mode=WAL` on file-backed databases
- concurrent read and write do not produce `Database is locked`

## Out Of Scope

- SQLAlchemy or Alembic integration
- automatic schema generation from models
- graph storage, which belongs to LadybugDB
