# Task 41: Deterministic Idiom Discovery

- **Milestone:** M41
- **Depends on:** M5 (Idiom Workflow), M39 (Deterministic Glossary Discovery)
- **Status:** Active
- **Supersedes:** LLM-first idiom detection in `lld-05-idioms.md`

## Goal

Replace idiom detection's LLM-first scan with a deterministic NLP-first candidate pipeline. The LLM shifts to batch validation and policy guidance: it judges pre-screened candidates, classifies usage, recommends literal/idiomatic/preserve rendering strategy, and returns schema-constrained JSON with reason codes.

## Scope

In:

- deterministic idiom candidate generation:
  - idiom lexicon exact match
  - HanLP segmentation + POS signals
  - four-character expression mining
  - fixed-pattern phrase mining
  - PMI / C-value phrase detection
  - repeated non-compositional phrase detection
- idiom feature metadata on candidates: source strategies, frequency, chapter coverage, context snippets, dictionary match, literal and idiomatic meanings when known
- deterministic prefilter rules to remove ordinary noun phrases, names/titles/locations/techniques, compositional phrases without idiom evidence, and low-score candidates
- LLM batch evaluator with schema JSON only; no raw-chapter LLM discovery path
- embedding clustering for variant forms and consistency with existing idiom policies
- tests-first update of obsolete LLM-discovery idiom tests

Out:

- changing packet consumption shape for approved idiom policies
- changing translation pass prompts outside existing idiom rendering / meaning prompts
- large curated idiom dictionary work beyond a small packaged seed file
- reviving full-chapter LLM discovery as fallback

## Owned Files Or Modules

Primary:

- `src/resemantica/idioms/`
- `src/resemantica/db/idiom_repo.py`
- `src/resemantica/db/sqlite.py`
- `src/resemantica/settings.py`
- `src/resemantica/llm/prompts/`
- `tests/idioms/`

Shared support:

- shared HanLP segmenter extracted from glossary without breaking `resemantica.glossary.segmenter`
- CLI / orchestration only for optional non-breaking idiom discovery flags

## Interfaces To Satisfy

- LLD: `../20-lld/lld-41-deterministic-idiom-discovery.md`
- CLI remains: `uv run python -m resemantica.cli preprocess idioms --release <release_id>`
- `preprocess_idioms()` keeps its existing external role and output keys
- `review_idiom_candidates()` and `promote_idiom_candidates()` remain compatible with existing review files
- `IdiomPolicy` remains the downstream authority consumed by packets and exact matching

## Execution Checklist

### Phase 1: Documentation And Tests First

- [x] **1.1** Add task and LLD for deterministic idiom discovery
- [x] **1.2** Update milestone index and idiom LLD cross-reference
- [ ] **1.3** Update obsolete idiom pipeline tests so raw-chapter LLM detection is no longer the expected path
- [ ] **1.4** Add unit tests for idiom candidate generation, scoring, filtering, evaluator parsing, and clustering

### Phase 2: Candidate Generation

- [ ] **2.1** Add packaged idiom seed lexicon and loader
- [ ] **2.2** Add idiom raw candidate / scored candidate models
- [ ] **2.3** Implement lexicon exact matching
- [ ] **2.4** Implement four-character expression mining
- [ ] **2.5** Implement HanLP/POS and fixed-pattern phrase mining
- [ ] **2.6** Implement repeated phrase and PMI/C-value scoring

### Phase 3: Filtering And Evaluation

- [ ] **3.1** Extend `IdiomCandidate` with nullable deterministic metadata fields
- [ ] **3.2** Extend SQLite schema and repo read/write paths for new fields
- [ ] **3.3** Implement deterministic prefilter rules
- [ ] **3.4** Add `idiom_evaluate.txt` and batch evaluator
- [ ] **3.5** Wire evaluator results to candidate status and metadata

### Phase 4: Clustering And Pipeline Integration

- [ ] **4.1** Implement embedding-based idiom clustering with graceful fallback when critic extras are unavailable
- [ ] **4.2** Compare clusters against existing approved idiom policies and copy known renderings where safe
- [ ] **4.3** Rewire `extract_idioms()` / `preprocess_idioms()` to use deterministic discovery plus evaluator
- [ ] **4.4** Preserve existing translate, review, promote, and exact-match behavior downstream
- [ ] **4.5** Add optional CLI args: `--eval-batch-size`, `--skip-llm-eval`, `--dedup-threshold`, `--score-threshold`

## Tests Or Smoke Checks

Targeted:

```bash
uv run --extra dev pytest tests/idioms -q
uv run --extra dev pytest tests/glossary tests/packets tests/cli -q
uv run --extra dev ruff check src/resemantica tests
uv run --extra dev mypy src/resemantica
```

Required scenarios:

- deterministic extraction finds lexicon idioms without LLM calls
- deterministic extraction finds repeated four-character idiom-like phrases
- filters reject ordinary noun phrases and glossary-like names/locations/techniques
- LLM evaluator parses schema-constrained JSON and rejects malformed rows safely
- clustering reuses existing policy rendering for known variant forms
- existing review, promotion, and packet exact-match tests remain valid

## Done Criteria

- [ ] Raw chapter text is not sent to `idiom_detect.txt` for discovery in the normal path
- [ ] Candidate generation is reproducible without an LLM
- [ ] LLM calls, when enabled, evaluate batches of candidates only
- [ ] New metadata is nullable/backward-compatible for existing databases
- [ ] Approved `IdiomPolicy` downstream contract remains stable
- [ ] All targeted tests pass, `ruff check` clean, `mypy` clean
