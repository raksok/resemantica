# Repo Map

## Current State

Current top-level files:

- `SPEC.md`, `ARCHITECT.md`, `DATA_CONTRACT.md`, `IMPLEMENTATION_PLAN.md`: project contracts and milestone plan
- `docs/`: implementation-facing documentation suite
- `main.py`: placeholder entrypoint, expected to be replaced or superseded by `src/resemantica/`
- `pyproject.toml`: Python project metadata

There is no production package layout yet. Until `src/resemantica/` exists, new implementation work should follow the target structure defined in `../10-architecture/module-boundaries.md`.

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
