# Task 03: Canonical Glossary

- **Milestone:** M3
- **Depends on:** M1
- **Status:** Completed on 2026-04-24 (implementation + validation complete)

## Goal

Implement candidate discovery, candidate translation, validation, and promotion into locked glossary authority state.

## Scope

In:

- SQLite glossary repositories
- discovery and promotion commands
- deterministic conflict handling

Out:

- summary generation
- fuzzy retrieval

## Owned Files Or Modules

- `src/resemantica/db/`
- `src/resemantica/llm/`
- glossary service modules if introduced
- `tests/glossary/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-03-glossary.md`
- storage rules: `../10-architecture/storage-topology.md`

## Tests Or Smoke Checks

- discovery writes candidates only
- promotion transaction test
- duplicate/conflict test

Execution status:

- [x] `uv run --extra dev pytest tests/glossary tests/translation tests/epub` passed (`16 passed`)
- [x] `uv run --extra dev ruff check src/resemantica tests/glossary tests/translation tests/epub docs/30-operations/repo-map.md` passed
- [x] `uv run --extra dev mypy src/resemantica` passed

## Done Criteria

- [x] locked glossary is separate from candidates
- [x] promotion is explicit and validated
- [x] exact-match lookup behavior is covered by tests
