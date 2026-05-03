# Task 03: Canonical Glossary

- **Milestone:** M3
- **Depends on:** M1
- **Status:** Completed on 2026-04-24 (implementation + validation complete)
- **Post-MVP Improvements:** 2026-05-03

## Goal

Implement candidate discovery, candidate translation, validation, and promotion into locked glossary authority state.

## Scope

In:

- SQLite glossary repositories
- discovery and promotion commands
- deterministic conflict handling
- content-based pruning (BGE-M3 embedding critic)
- human-override review workflow

Out:

- summary generation
- fuzzy retrieval

## Owned Files Or Modules

- `src/resemantica/db/`
- `src/resemantica/llm/`
- glossary service modules (`glossary/critic.py`, `glossary/validators.py`)
- `tests/glossary/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-03-glossary.md`
- storage rules: `../10-architecture/storage-topology.md`

## Tests Or Smoke Checks

- discovery writes candidates only
- promotion transaction test
- duplicate/conflict test
- deterministic filter catches date patterns and stop-list terms
- BGE-M3 critic scores are stored and do not block translation at threshold=0

Execution status:

- [x] `uv run --extra dev pytest tests/glossary tests/translation tests/epub` passed (`16 passed`)
- [x] `uv run --extra dev ruff check src/resemantica tests/glossary tests/translation tests/epub docs/30-operations/repo-map.md` passed
- [x] `uv run --extra dev mypy src/resemantica` passed

## Done Criteria

- [x] locked glossary is separate from candidates
- [x] promotion is explicit and validated
- [x] exact-match lookup behavior is covered by tests

## Post-MVP Improvements (2026-05-03)

Three categories of quality-of-life improvements applied after initial M3 completion:

### 1. Candidate Quality Filtering

Three-tier approach to reduce LLM false-positive glossary terms:

**Tier 1 — Deterministic filter** (`glossary/validators.py:apply_deterministic_filter()`):
- Date/time pattern regex (catches `二月二`-style false positives)
- Curated stop-list of ~30 common Chinese nouns observed as frequent LLM false positives
- Near-zero false positive risk — only exact pattern matches and exact word matches

**Tier 2 — Prompt improvement** (`llm/prompts/glossary_discover.txt`):
- Added concrete negative examples showing what NOT to pick
- Bumped prompt version to v2.0 (invalidates LLM response cache)

**Tier 3 — BGE-M3 embedding critic** (`glossary/critic.py`):
- Loads a reference vocabulary of ~100 common Chinese words
- Embeds each candidate term with BGE-M3 via `sentence-transformers`
- Scores by cosine similarity to nearest reference word (1.0 = maximally unlike common vocab)
- Prunes candidates below `pruning_threshold` (default 0.3, set to 0 for eval-only)
- Score stored in `glossary_candidates.critic_score` for audit and threshold tuning
- Evaluation workflow: run with `--pruning-threshold 0`, collect scores, find optimal threshold via precision/recall against known good/bad candidates

### 2. Translation Reliability

- Restructured `glossary_translate.txt` to use explicit section headers (`CONTEXT:`, `This is text of {CATEGORY}, Translate...`)
- Added response post-processing in `LLMClient.translate_glossary_candidate()` to strip label prefixes and chain-of-thought leftovers
- Bumped prompt version to v2.0

### 3. Human Override Workflow

- New CLI command: `preprocess glossary-review` — dumps translated candidates to a human-editable JSON review file
- Modified `preprocess glossary-promote --review-file PATH` — reads edited file, applies overrides, deletions, and additions, then runs standard validation + promotion
- Review file uses `review_schema_version` field for forward compatibility
- No DB schema changes needed — review file is a standalone artifact
