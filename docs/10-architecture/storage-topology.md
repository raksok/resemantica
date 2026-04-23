# Storage Topology

## Stores

### SQLite

Purpose:

- authority state
- promotable working state
- operational state

Primary datasets:

- glossary candidates
- locked glossary
- summaries
- idioms
- packet metadata
- checkpoints
- run metadata
- cleanup bookkeeping

File location:

- `artifacts/resemantica.db`

### LadybugDB

Purpose:

- graph-native entities
- aliases
- appearances
- relationships

Constraints:

- chapter-safe filtering required
- provisional and confirmed state must remain separable

File location:

- `artifacts/graph.ladybug`

Client:

- **Package:** `ladybug` (install via `uv add ladybug`)
- **Import:** `import ladybug as lb`
- **NOT** `kuzu` — LadybugDB was formerly Kuzu but the package and import are now `ladybug`
- API reference: https://docs.ladybugdb.com/client-apis/python
- Embedded, serverless, Cypher query language

### MLflow

Purpose:

- run metadata
- metrics
- artifacts
- run comparison

Backend:

- SQLite tracking at `artifacts/mlflow.db`
- Operator views via `mlflow ui --backend-store-uri sqlite:///artifacts/mlflow.db`

Constraint:

- tracking must mirror orchestration behavior, not become an alternate execution path.

## Path Model

Target artifact root:

```text
artifacts/
  releases/{release_id}/
    extracted/
    glossary/
    summaries/
    packets/
    runs/{run_id}/
      translation/
      validation/
      events/
      reconstruction/
      cleanup/
```

The exact path rules are defined in `../30-operations/artifact-paths.md`.

## Versioning Rules

- Any runtime-affecting dataset or artifact must carry `schema_version`.
- Derived artifacts must include upstream hashes.
- Immutable artifacts get new versions instead of in-place mutation.
- Operational rows may update status fields, timestamps, and retry counts.
