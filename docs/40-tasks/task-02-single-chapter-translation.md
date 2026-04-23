# Task 02: Single-Chapter Translation MVP

- **Milestone:** M2
- **Depends on:** M1
- **Status:** Completed on 2026-04-24 (implementation + validation complete)

## Goal

Implement single-chapter Pass 1 and Pass 2 translation with placeholder-safe validation and checkpoints.

## Scope

In:

- create `translation/` and `llm/` foundations
- add `translate-chapter` CLI command
- persist pass artifacts and checkpoints

Out:

- Pass 3
- packets
- production orchestration

## Owned Files Or Modules

- `src/resemantica/translation/`
- `src/resemantica/llm/`
- `src/resemantica/cli.py`
- `tests/translation/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-02-single-chapter-translation.md`
- path rules: `../30-operations/artifact-paths.md`

## Tests Or Smoke Checks

- placeholder preservation test
- Pass 2 correction test
- resume from successful Pass 1 test

Execution status:

- [x] `uv run --extra dev pytest tests/translation tests/epub` passed (`12 passed`)
- [x] `uv run --extra dev ruff check src/resemantica tests/translation tests/epub docs/30-operations/repo-map.md` passed
- [x] `uv run --extra dev mypy src/resemantica` passed

## Done Criteria

- [x] a single chapter can produce pass artifacts and validation reports
- [x] structural failures halt the run
- [x] checkpoint semantics match the LLD
