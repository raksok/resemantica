# Repo Map

## Current State

Current top-level files:

- `SPEC.md`, `ARCHITECT.md`, `DATA_CONTRACT.md`, `IMPLEMENTATION_PLAN.md`: project contracts and milestone plan
- `docs/`: implementation-facing documentation suite
- `embedding/`: ignored local embedding model cache populated at runtime or by `scripts/download_embedding_model.py`
- `src/resemantica/`: active package root for milestone implementation
- `scripts/`: operator utility scripts
- `tests/`: milestone test suites (`db/`, `epub/`, `translation/`, `glossary/`, `summaries/`, `idioms/`, `graph/`, `packets/`, `orchestration/`)
- `pyproject.toml`: Python project metadata

Implemented package layout (M1 slice):

- `src/resemantica/cli.py`: CLI entrypoint, command router, and Rich result summaries that preserve key/value output
- `src/resemantica/cli_progress.py`: CLI Rich live progress subscriber with start/elapsed time, counters, and log panel
- `src/resemantica/embedding_models.py`: project-local Hugging Face embedding model cache resolution and download helper
- `src/resemantica/settings.py`: config loading, batch-order chunk settings, and release-scoped path derivation for artifacts, SQLite, and LadybugDB
- `src/resemantica/epub/`: EPUB extractor, parser, placeholders, validators, and rebuild; rebuild consumes existing translated artifacts even for non-story chapters
- `src/resemantica/db/sqlite.py`: SQLite connection helpers and the inline application schema source of truth, including `chunk_checkpoints`
- `tests/db/`: SQLite schema creation tests and source guard for inline-schema-only behavior

Implemented package layout (M2 slice):

- `src/resemantica/llm/`: LLM client and prompt loading helpers
- `src/resemantica/llm/prompts/translate_pass1.txt`, `translate_pass2.txt`: prompt templates with version headers
- Analyst-facing prompt files under `src/resemantica/llm/prompts/` use prompt-local anti-restart policy text: one reasoning pass is allowed, recursive restarts/self-correction loops are discouraged, and prompt version bumps invalidate stale analyst outputs.
- `src/resemantica/translation/`: pass1/pass2, validators, checkpoints, bundle-context loading, translate-chapter pipeline; missing packet bundle context emits `translate-chapter.bundle_context_missing`, and batched range chunking is orchestrated by `orchestration.runner`
- `tests/translation/`: M2 translation tests

Implemented package layout (M3 slice):

- `src/resemantica/glossary/`: candidate discovery, filter/eval/scoring/dedup/finalization events, translation vote/finalization events, review CSV/JSON export/import, promotion validators, and glossary pipeline orchestration
- `src/resemantica/db/glossary_repo.py`: SQLite repository for glossary candidates, translation votes, vote-resume lookup helpers, locked glossary, and conflicts
- `src/resemantica/llm/prompts/glossary_discover.txt`, `glossary_translate.txt`: M3 glossary prompt files
- `tests/glossary/`: glossary discovery, conflict, transaction, and precedence tests

### Glossary translate resume

Glossary translation votes are durable per model. Reruns with the same `-r`, same `-R`, and same model configuration skip existing votes for `(release_id, run_id, model_name)` and continue from missing votes unless `--force` is used. If a local model server crashes during one model batch, completed votes from earlier batches remain saved.

For operator recovery, rerun the same command without `--force`. Keep the model list unchanged when the goal is to let the interrupted model continue from its first missing vote. Change `models.preprocess_translator_names` only when intentionally abandoning a crashing model and resolving from the remaining configured model votes.

Implemented package layout (M4 slice):

- `src/resemantica/summaries/`: chapter summary generation, deterministic validation, LLM content-validation gates, chunked batch-order execution, summary derivation pipeline, and English checkpoint backfill/resume from approved Chinese continuity rows
- `src/resemantica/db/summary_repo.py`: SQLite repository for summary drafts, validated Chinese summaries, and derived English summaries; validated-summary reads are approved-only by default with explicit audit access for failed rows
- `src/resemantica/llm/prompts/summary_zh_structured.txt`, `summary_zh_validate.txt`, `summary_en_derive.txt`, `summary_graph_continuity_update.txt`: summary prompt files; the structured prompt is schema-first and versioned to invalidate stale cache entries after prompt changes
- `tests/summaries/`: continuity conflict, glossary conflict, future-leak, deterministic story rebuild, schema recovery, and fatal LLM validation flag tests
- Summary schema recovery is scoped to `src/resemantica/summaries/generator.py`: after one targeted retry, known recoverable structured-summary drift can be defaulted or dropped with warning codes that are written to summary artifacts under `warnings`.
- Summary compact continuity recovery is scoped to `src/resemantica/summaries/derivation.py`: over-budget `story_so_far_zh_compact` drafts are repaired before caching, stale over-budget cache entries are replaced with under-budget repaired text, and repair success/failure events are emitted through the summary pipeline callback.
- `src/resemantica/summaries/continuity.py`: post-graph graph-grounded compact continuity refresh, deterministic chapter-safe graph anchor formatting, and `preprocess-continuity.chapter_failed` event emission for per-chapter failures

Implemented package layout (M5 slice):

- `src/resemantica/idioms/`: idiom extraction, deterministic validation, review CSV/JSON export/import, exact-match hooks, and idiom preprocessing pipeline
- `src/resemantica/db/idiom_repo.py`: SQLite repository for idiom candidates, translation votes, policies, and conflicts
- `src/resemantica/llm/prompts/idiom_detect.txt`: M5 idiom detection prompt file
- `tests/idioms/`: idiom extraction, duplicate/conflict, storage, and retrieval precedence tests

Implemented package layout (M6 slice):

- `src/resemantica/graph/`: graph models, Ladybug client wrapper, deterministic extraction, validation, filtering, and preprocessing pipeline; confirmed graph state feeds the post-graph continuity refresh, and graph validation failures emit `preprocess-graph.validation_failed`
- `src/resemantica/db/graph_repo.py`: SQLite repository for deferred entities, graph extraction drafts, and graph snapshot metadata
- `tests/graph/`: alias reveal gating, relationship chapter eligibility, validation, deferred lifecycle, and snapshot metadata tests

Implemented package layout (M7 slice):

- `src/resemantica/graph/models.py`: world-model edge types (`MEMBER_OF`, `LOCATED_IN`, `HELD_BY`, `RANKED_AS`) and `WorldModelEdge` contract
- `src/resemantica/graph/extractor.py`: deterministic hierarchy/containment/role-state extraction with chapter-scoped interval transitions
- `src/resemantica/graph/filters.py`: `get_hierarchy_context()`, `get_revealed_lore()`, and local world-model edge selectors
- `src/resemantica/graph/validators.py`: unsupported edge-type rejection and reveal-safe lore validation checks
- `tests/graph/`: M7 tests for role-state transitions, containment visibility, reveal-safe lore gating, and unsupported expansion rejection

Implemented package layout (M8 slice):

- `src/resemantica/packets/`: chapter packet schemas, graph-enriched packet builder, graph-grounded continuity preference, approved-only summary consumption, paragraph bundle derivation, and stale detection
- `src/resemantica/db/packet_repo.py`: SQLite packet metadata repository for reproducibility and stale checks
- `src/resemantica/llm/tokens.py`: cl100k token counting utility for packet/bundle budgeting with 5% safety-buffer enforcement
- `src/resemantica/cli.py`: `packets build` command wiring
- `tests/packets/`: packet schema, provenance, stale rebuild, graph filtering, size budget, and retrieval precedence tests

Implemented package layout (M9 slice):

- `src/resemantica/translation/pass3.py`: Pass 3 readability polish with fidelity/terminology guardrails
- `src/resemantica/translation/risk.py`: deterministic paragraph risk classifier using D21 weighted formula
- `src/resemantica/translation/validators.py`: `validate_pass3_integrity()` for terminology drift and meaning drift detection
- `src/resemantica/translation/pipeline.py`: Pass 3 integration with risk-based skip, integrity validation, and fallback to Pass 2
- `src/resemantica/llm/prompts/translate_pass3.txt`: Pass 3 prompt template with version header
- `tests/translation/test_pass3_and_risk.py`: risk scoring, threshold edge, sub-score saturation, skip behavior, integrity fallback, and chapter-level validation tests

Implemented package layout (M10 slice):

- `src/resemantica/orchestration/`: centralized run control, stage ordering, retries, resume behavior, cleanup planning, and structured events
- `src/resemantica/orchestration/models.py`: `StageResult`, `legal_transition()`, `next_stage()`, `STAGE_ORDER` including `preprocess-continuity` between graph and packet build
- `src/resemantica/orchestration/runner.py`: `run_production()` and `run_stage()` for resumable production, stage execution, transition validation, gate handling, auto review artifact generation for unresolved votes, batched translation pass-failure events, and chunk checkpoint updates
- `src/resemantica/orchestration/chunk_checkpoints.py`: durable chunk checkpoint repository used by summary and batched translation cleanup boundaries
- `src/resemantica/orchestration/retry_failed.py`: durable failed-unit planner and executor for `run retry-failed`, including `llm_content_validation_failed` summary recovery
- `src/resemantica/orchestration/resume.py`: `resume_run()` for checkpoint-based resume
- `src/resemantica/orchestration/cleanup.py`: shared cleanup scopes plus `plan_cleanup()` and `apply_cleanup()` for validated, two-step cleanup workflow, including stale-plan protection and `last-good-chunk`
- `src/resemantica/orchestration/events.py`: `emit_event()` for structured event emission, tracking persistence, and paired structured Loguru records for operational signals
- `src/resemantica/tracking/`: event and run state models with SQLite persistence
- `src/resemantica/tracking/models.py`: `Event` and `RunState` dataclasses with schema versioning
- `src/resemantica/tracking/repo.py`: SQLite persistence for events and run state
- `src/resemantica/cli.py`: `run` command with `production`, `resume`, `retry-failed`, `cleanup-plan`, `cleanup-apply` subcommands
- `tests/orchestration/`: stage transition, event emission, chunk checkpoints, cleanup plan/apply, batched translation, resume, run stage, and logging contract guard tests
- `tests/translation/test_bundle_context_logging.py`: bundle-context missing event tests for absent packet metadata, missing bundle files, and empty bundle rows

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
