# Task 14: Observability and Evaluation (M13)

- **Milestone:** M13
- **Depends on:** M10

## Goal

Implement local run observability, MLflow tracking, golden-set evaluation, and comparison-friendly quality reports.

## Scope

In:

- MLflow helpers for parameters, metrics, artifacts, and summaries
- instrumentation of orchestration-visible stages
- golden-set schema and evaluation runner
- local reports or dashboards for warning and quality trends

Out:

- cloud analytics platforms
- fully automated experiment management beyond local comparison
- alternate execution paths inside tracking code

## Owned Files Or Modules

- `src/resemantica/tracking/`
- `tests/tracking/`
- `tests/golden_set/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-14-observability.md`
- MLflow backend: `sqlite:///artifacts/mlflow.db`
- data contract: event stream records and validation reports in `../../DATA_CONTRACT.md`

## Tests Or Smoke Checks

- MLflow metadata and artifact logging with a local SQLite backend or mocked MLflow client
- golden-set fixture load and benchmark execution
- metric calculation for fidelity, terminology, structure, and readability
- instrumentation does not block core workflow success

## Done Criteria

- run metadata includes model names, prompt versions, packet versions, warning counts, and validation outcomes
- a golden-set run can be executed and compared across runs
- dashboards or reports expose retry, warning, glossary conflict, and high-risk paragraph trends
- tracking remains a consumer of orchestration events, not an alternate workflow owner
