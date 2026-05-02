# Task 31: Absorb DB Migrations Into Code

## Goal

Replace the 10-file migration system (`db/migrations/` + `apply_migrations()`) and the separate `ensure_extraction_schema()` with a single consolidated `ensure_full_schema()` function, so all future schema changes are made inline in code rather than via numbered SQL migration files.

## Scope

In:

- Merge all 10 migration `.sql` files into one `ensure_full_schema()` function in `db/sqlite.py` using `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`.
- Absorb ALTER TABLE additions (migrations 008–010) into the base `CREATE TABLE` statements.
- Absorb `extracted_chapters` and `extracted_blocks` tables from `extraction_repo.py` into the consolidated schema.
- Replace `apply_migrations()` with a direct call to `ensure_full_schema()` inside `ensure_schema()`.
- Update `extraction_repo.py` to call `ensure_schema(conn, "extraction")` instead of its own `ensure_extraction_schema()`.
- Delete `db/migrations/` directory with all 10 `.sql` files.
- Delete `apply_migrations()` function from `db/sqlite.py`.
- Remove `schema_migrations` tracking table creation (no longer needed).
- Remove orphan `schema_migrations` table: add `DROP TABLE IF EXISTS schema_migrations` at the end.

Out:

- Changing any table column types, constraints, or semantics.
- Adding any new tables or columns beyond what the 10 migrations + extraction tables already define.
- Any test changes — existing tests call `ensure_schema()` which is the entry point, behaviour is identical.

## Owned Files Or Modules

- `src/resemantica/db/sqlite.py`
- `src/resemantica/db/extraction_repo.py`
- `src/resemantica/db/migrations/` (delete directory)
- `docs/20-lld/lld-31-absorb-db-migrations.md`
- `docs/40-tasks/task-31-absorb-db-migrations.md`

## Interfaces To Satisfy

### `ensure_schema(conn, name)`

Signature unchanged. Behaviour: calls `ensure_full_schema()` instead of `apply_migrations()`. The `name` parameter remains unused.

### `ensure_full_schema(conn)` — new

```python
def ensure_full_schema(conn: sqlite3.Connection) -> None:
    """Create all application tables if they don't exist.
    Safe to call repeatedly — uses IF NOT EXISTS everywhere.
    """
```

Contains all `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` statements from the 10 migrations plus the extraction tables, with ALTER TABLE columns merged into base CREATE statements.

### `ensure_extraction_schema(conn)` — removed

Callers in `extraction_repo.py` switch to `ensure_schema(conn, "extraction")`.

### `record_extraction_metadata`

Still calls `ensure_schema(conn, "extraction")` instead of `ensure_extraction_schema(conn)`.

## Tests Or Smoke Checks

- Existing full test suite passes: `uv run pytest`.
- Run `uv run ruff check src tests`.
- No new tests needed — existing tests exercise `ensure_schema()` through all repos.

## Done Criteria

- `db/migrations/` directory deleted.
- `apply_migrations()` and `ensure_extraction_schema()` removed.
- Single `ensure_full_schema()` creates all 16 tables + indexes idempotently.
- All existing tests pass.
- Future schema changes only need editing `ensure_full_schema()` — no migration files.
