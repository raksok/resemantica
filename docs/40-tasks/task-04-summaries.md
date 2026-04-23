# Task 04: Summary Memory

- **Milestone:** M4
- **Depends on:** M1

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

## Done Criteria

- Chinese authority and English derived datasets are separate
- validation rules are enforced in code
- provenance hashes are persisted for English outputs
