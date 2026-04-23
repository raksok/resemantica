# Task 04: Summary Memory

- **Milestone:** M4
- **Depends on:** M1
- **Status:** Completed on 2026-04-24 (implementation + validation complete)

## Goal

Implement validated Chinese summaries, derived English summaries, and deterministic story-so-far derivation.

## Scope

In:

- summary repositories
- summary generation and validation
- English derivation with provenance

Out:

- packet builder
- deep graph integration

## Owned Files Or Modules

- `src/resemantica/summaries/`
- `src/resemantica/db/`
- `tests/summaries/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-04-summaries.md`

## Tests Or Smoke Checks

- future-knowledge leak detection
- glossary conflict handling
- deterministic `story_so_far_zh` rebuild

Execution status:

- [x] `uv run --extra dev pytest tests/summaries tests/glossary tests/translation tests/epub` passed (`21 passed`)
- [x] `uv run --extra dev ruff check src/resemantica tests/summaries tests/glossary tests/translation tests/epub` passed
- [x] `uv run --extra dev mypy src/resemantica` passed
- [x] `uv run python -m resemantica.cli preprocess --help` passed (includes `summaries`)
- [x] `uv run python -m resemantica.cli preprocess summaries --help` passed

## Done Criteria

- [x] Chinese authority and English derived datasets are separate
- [x] validation rules are enforced in code
- [x] provenance hashes are persisted for English outputs
