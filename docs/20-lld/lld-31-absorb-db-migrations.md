# LLD 31: Absorb DB Migrations Into Code

## Summary

Replace the 10-file numbered SQL migration system and the separate inline DDL in `extraction_repo.py` with a single `ensure_full_schema()` function that defines all tables and indexes inline using idempotent DDL (`IF NOT EXISTS`). Future schema changes edit the function directly — no migration files.

## Problem Statement

The project has two conflicting schema management approaches:

| Approach | File | Mechanism |
|---|---|---|
| Migration files | `db/sqlite.py` + `db/migrations/` (10 `.sql` files) | `apply_migrations()` scans numbered files, tracks applied versions in `schema_migrations` table |
| Inline DDL | `db/extraction_repo.py` | Raw `CREATE TABLE IF NOT EXISTS` in `ensure_extraction_schema()`, no version tracking |

Neither approach provides value in pre-alpha. The migration files add ceremony (numbered files, version tracking) for a codebase where everyone deletes the DB on schema changes. The separate extraction schema duplicates the same pattern (DDL in code) but outside the migration system. Consolidating into one function eliminates the migration directory, removes the version tracking overhead, and makes future schema changes a single code edit.

## Design

### Replaced: `apply_migrations()` + `ensure_extraction_schema()`

Both are removed. In their place, `ensure_schema(conn, name)` calls a new `ensure_full_schema(conn)`.

### `ensure_full_schema(conn)`

Single function in `db/sqlite.py`. Contains all table and index DDL as `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` statements executed via `conn.executescript()`.

All columns added by migration ALTER TABLE statements (008, 009, 010) are inlined into their base `CREATE TABLE`:

| Migration | Table | Columns | Now in |
|---|---|---|---|
| 008 | `glossary_candidates` | `analyst_model_name`, `analyst_prompt_version` | Inline in `CREATE TABLE glossary_candidates` |
| 009 | `summary_drafts` | `is_story_chapter` | Inline in `CREATE TABLE summary_drafts` |
| 010 | `idiom_candidates` | `translation_run_id`, `translator_model_name`, `translator_prompt_version` | Inline in `CREATE TABLE idiom_candidates` |

The `extracted_chapters` and `extracted_blocks` tables (currently in `extraction_repo.py`) are added to the same function.

The `schema_migrations` tracking table is no longer created. It is dropped at the end if it exists: `DROP TABLE IF EXISTS schema_migrations`.

The `name` parameter of `ensure_schema()` remains for API compatibility but is unused — all tables are always created.

### `extraction_repo.py` changes

`ensure_extraction_schema()` is removed. `record_extraction_metadata()` calls `ensure_schema(conn, "extraction")` instead.

### Deleted

- `src/resemantica/db/migrations/` — entire directory (10 `.sql` files)

### Future schema changes

| Change | How |
|---|---|
| New table | Add `CREATE TABLE IF NOT EXISTS` to `ensure_full_schema()` |
| New column | Add column to the `CREATE TABLE` statement if table doesn't exist yet; for existing DBs, add a `try/except OperationalError` guard or accept that devs delete their DB |
| New index | Add `CREATE INDEX IF NOT EXISTS` to `ensure_full_schema()` |

Since this is pre-alpha, the simplest approach for new columns on existing tables is accepted: developers delete `resemantica.db` and `graph.ladybug` when pulling schema changes. The `IF NOT EXISTS` pattern handles new installs cleanly.

## Table Inventory

All 16 tables created by `ensure_full_schema()`:

| Table | Source migration | Notes |
|---|---|---|
| `runs` | 001 | |
| `checkpoints` | 001 | |
| `translation_checkpoints` | 002 | |
| `glossary_candidates` | 003 + 008 | 008 columns inlined |
| `locked_glossary` | 003 | |
| `glossary_conflicts` | 003 | |
| `summary_drafts` | 004 + 009 | 009 column inlined |
| `validated_summaries_zh` | 004 | |
| `derived_summaries_en` | 004 | |
| `idiom_candidates` | 005 + 010 | 010 columns inlined |
| `idiom_policies` | 005 | |
| `idiom_conflicts` | 005 | |
| `deferred_entities` | 006 | |
| `graph_snapshots` | 006 | |
| `packet_metadata` | 007 | |
| `extracted_chapters` | extraction_repo | Moved inline |
| `extracted_blocks` | extraction_repo | Moved inline |

## Backward Compatibility

| Scenario | Behaviour |
|---|---|
| Existing DB with `schema_migrations` table | `DROP TABLE IF EXISTS schema_migrations` removes it — harmless, no code references it |
| Existing DB with all tables already created | `CREATE TABLE IF NOT EXISTS` is no-op; already-present columns in CREATE are no-op |
| New DB (clean slate) | All tables created in one `executescript()` call |

## Out Of Scope

- Changing any column types, constraints, nullability, or semantics.
- Adding any new tables beyond what the 10 migrations + extraction already define.
- Any test changes — all existing callers use `ensure_schema()` which keeps the same signature.
- LadybugDB graph schema — managed by the `ladybug` package itself.
