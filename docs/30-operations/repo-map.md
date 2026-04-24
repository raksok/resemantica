# Repo Map

## Current State

Current top-level files:

- `SPEC.md`, `ARCHITECT.md`, `DATA_CONTRACT.md`, `IMPLEMENTATION_PLAN.md`: project contracts and milestone plan
- `docs/`: implementation-facing documentation suite
- `src/resemantica/`: active package root for milestone implementation
- `tests/`: milestone test suites (`epub/`, `translation/`, `glossary/`, `summaries/`, `idioms/`, `graph/`)
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

Implemented package layout (M3 slice):

- `src/resemantica/glossary/`: candidate discovery, promotion validators, and glossary pipeline orchestration
- `src/resemantica/db/glossary_repo.py`: SQLite repository for glossary candidates, locked glossary, and conflicts
- `src/resemantica/db/migrations/003_glossary.sql`: glossary tables and constraints
- `src/resemantica/llm/prompts/glossary_discover.txt`, `glossary_translate.txt`: M3 glossary prompt files
- `tests/glossary/`: glossary discovery, conflict, transaction, and precedence tests

Implemented package layout (M4 slice):

- `src/resemantica/summaries/`: chapter summary generation, deterministic validation, and summary derivation pipeline
- `src/resemantica/db/summary_repo.py`: SQLite repository for summary drafts, validated Chinese summaries, and derived English summaries
- `src/resemantica/db/migrations/004_summaries.sql`: summary tables and constraints
- `src/resemantica/llm/prompts/summary_zh_structured.txt`, `summary_en_derive.txt`: M4 summary prompt files
- `tests/summaries/`: continuity conflict, glossary conflict, future-leak, and deterministic story rebuild tests

Implemented package layout (M5 slice):

- `src/resemantica/idioms/`: idiom extraction, deterministic validation, exact-match hooks, and idiom preprocessing pipeline
- `src/resemantica/db/idiom_repo.py`: SQLite repository for idiom candidates, policies, and conflicts
- `src/resemantica/db/migrations/005_idioms.sql`: idiom tables and constraints
- `src/resemantica/llm/prompts/idiom_detect.txt`: M5 idiom detection prompt file
- `tests/idioms/`: idiom extraction, duplicate/conflict, storage, and retrieval precedence tests

Implemented package layout (M6 slice):

- `src/resemantica/graph/`: graph models, Ladybug client wrapper, deterministic extraction, validation, filtering, and preprocessing pipeline
- `src/resemantica/db/graph_repo.py`: SQLite repository for deferred entities and graph snapshot metadata
- `src/resemantica/db/migrations/006_graph.sql`: deferred entity and graph snapshot tables
- `tests/graph/`: alias reveal gating, relationship chapter eligibility, validation, deferred lifecycle, and snapshot metadata tests

Implemented package layout (M7 slice):

- `src/resemantica/graph/models.py`: world-model edge types (`MEMBER_OF`, `LOCATED_IN`, `HELD_BY`, `RANKED_AS`) and `WorldModelEdge` contract
- `src/resemantica/graph/extractor.py`: deterministic hierarchy/containment/role-state extraction with chapter-scoped interval transitions
- `src/resemantica/graph/filters.py`: `get_hierarchy_context()`, `get_revealed_lore()`, and local world-model edge selectors
- `src/resemantica/graph/validators.py`: unsupported edge-type rejection and reveal-safe lore validation checks
- `tests/graph/`: M7 tests for role-state transitions, containment visibility, reveal-safe lore gating, and unsupported expansion rejection

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
