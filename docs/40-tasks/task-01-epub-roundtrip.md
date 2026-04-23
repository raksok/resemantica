# Task 01: EPUB Round-Trip MVP

- **Milestone:** M1
- **Depends on:** —

## Goal

Implement deterministic EPUB unpack, extraction, validation, and rebuild so a supported EPUB can round-trip without translation changes.

## Scope

In:

- create `src/resemantica/epub/`
- add initial CLI command wiring for `epub-roundtrip`
- emit extraction and validation artifacts

Out:

- translation logic
- glossary and summaries

## Owned Files Or Modules

- `src/resemantica/cli.py`
- `src/resemantica/settings.py`
- `src/resemantica/epub/`
- `tests/epub/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-01-epub-roundtrip.md`
- artifact paths: `../30-operations/artifact-paths.md`
- package rules: `../10-architecture/module-boundaries.md`

## Tests Or Smoke Checks

- fixture EPUB round-trip test
- malformed XHTML report test
- stable block ordering test

## Done Criteria

- `epub-roundtrip` writes extracted artifacts and rebuilt EPUB
- validation reports are inspectable
- tests for the round-trip slice pass
- `repo-map.md` is updated if the real package layout now exists
