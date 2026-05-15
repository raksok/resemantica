# LLD: SQLite Inline Schema Cleanup

## Summary

`src/resemantica/db/sqlite.py` is the active SQLite schema source of truth. Runtime schema setup creates the current full schema inline through `ensure_full_schema()` and keeps `ensure_schema(conn, name)` as the public compatibility entrypoint.

## Decision

Remove migration-runner leftovers from active code:

- no numbered SQL migration directory
- no migration tracking table cleanup
- no runtime `ALTER TABLE` compatibility loops
- no production upgrade path for older local SQLite files

Fresh database creation is the supported path. Existing development databases may be deleted and recreated when schema shape changes.

## Behavior

`ensure_schema(conn, name)` delegates to `ensure_full_schema(conn)`. The `name` argument is retained for repository call-site compatibility, but the full application schema is created every time.

All current columns are declared in the base `CREATE TABLE IF NOT EXISTS` statements, including:

- `translation_checkpoints.packet_version_hash`
- deterministic glossary discovery columns on `glossary_candidates`
- deterministic idiom discovery columns on `idiom_candidates`

## Verification

`tests/db/test_sqlite_schema.py` verifies representative absorbed columns on a fresh SQLite database and guards active Python source against reintroducing migration-style schema patterns.
