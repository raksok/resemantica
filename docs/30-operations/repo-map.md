# Repo Map

## Current State

Current top-level files:

- `SPEC.md`, `ARCHITECT.md`, `DATA_CONTRACT.md`, `IMPLEMENTATION_PLAN.md`: project contracts and milestone plan
- `docs/`: implementation-facing documentation suite
- `src/resemantica/`: active package root for milestone implementation
- `tests/epub/`: EPUB round-trip and placeholder tests for M1
- `main.py`: placeholder entrypoint kept for compatibility with the starter project
- `pyproject.toml`: Python project metadata

Implemented package layout (M1 slice):

- `src/resemantica/cli.py`: CLI entrypoint (`epub-roundtrip`)
- `src/resemantica/settings.py`: config loading and path derivation
- `src/resemantica/epub/`: EPUB extractor, parser, placeholders, validators, rebuild
- `src/resemantica/db/sqlite.py`: SQLite connection and migration helpers
- `src/resemantica/db/migrations/001_initial.sql`: initial manual migration script

Implemented package layout (M2 slice):

- `src/resemantica/llm/`: LLM client and prompt loading helpers
- `src/resemantica/llm/prompts/translate_pass1.txt`, `translate_pass2.txt`: prompt templates with version headers
- `src/resemantica/translation/`: pass1/pass2, validators, checkpoints, translate-chapter pipeline
- `src/resemantica/db/migrations/002_translation_checkpoints.sql`: checkpoint table for chapter pass resume
- `tests/translation/`: M2 translation tests

## Target State

Primary code roots:

- `src/resemantica/`: application code
- `tests/`: unit, integration, and smoke tests
- `docs/`: implementation and operations docs

## Placement Rules

- add new execution code under `src/resemantica/`, not repo root
- add tests under `tests/`, not next to implementation modules
- add task briefs under `docs/40-tasks/`
- keep root markdown files limited to project-wide contracts unless a new root document is intentionally global

## Entry Points

Planned entrypoints:

- CLI: `src/resemantica/cli.py`
- TUI: `src/resemantica/tui/app.py`
- shared orchestration: `src/resemantica/orchestration/runner.py`

## Maintenance Rule

Update this file whenever:

- a new top-level directory is introduced
- the package layout changes materially
- a new operator entrypoint is added
- ownership boundaries move between subsystems
