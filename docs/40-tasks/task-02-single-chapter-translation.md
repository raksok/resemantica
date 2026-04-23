# Task 02: Single-Chapter Translation MVP

- **Milestone:** M2
- **Depends on:** M1

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

## Done Criteria

- a single chapter can produce pass artifacts and validation reports
- structural failures halt the run
- checkpoint semantics match the LLD
