# Task 03: Canonical Glossary

- **Milestone:** M3
- **Depends on:** M1

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

## Done Criteria

- locked glossary is separate from candidates
- promotion is explicit and validated
- exact-match lookup behavior is covered by tests
