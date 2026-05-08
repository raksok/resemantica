# Task 39: Deterministic Glossary Discovery

- **Milestone:** M39
- **Depends on:** M3 (Canonical Glossary — completed)
- **Supersedes:** Stage A of `lld-03-glossary.md` (LLM-based discovery)
- **Status:** Completed

## Goal

Replace the LLM-first glossary candidate discovery with a deterministic NLP-first pipeline. The LLM shifts from discoverer to batch evaluator, judging pre-screened candidates instead of scanning raw chapter text. This makes discovery reproducible, recall-complete, and far cheaper in LLM tokens.

## Scope

In:

- HanLP segmentation + POS + NER integration (`glossary/segmenter.py`)
- Deterministic candidate extraction with 5 strategies (`glossary/candidate_gen.py`)
- Corpus-level TF-IDF / C-value / composite scoring (`glossary/corpus_stats.py`)
- Expanded deterministic prefilter rules (`glossary/validators.py`)
- LLM batch evaluator for keep/reject decisions (`glossary/evaluator.py`)
- Embedding-based deduplication and alias clustering (`glossary/critic.py` rewrite)
- New prompt template for batch evaluation (`llm/prompts/glossary_evaluate.txt`)
- Data files: common words, webnovel seed dictionary, surname list (`glossary/data/`)
- Schema evolution: new nullable columns on `glossary_candidates`, new `glossary_alias_clusters` table
- Configuration: `[glossary]` section in `resemantica.toml` and `GlossaryConfig` dataclass
- CLI flag additions: `--eval-batch-size`, `--skip-llm-eval`, `--dedup-threshold`

Out:

- Glossary translation stage (Stage B — unchanged)
- Glossary promotion stage (Stage C — unchanged)
- Human review workflow (unchanged)
- Summary / idiom / graph pipelines
- TUI changes
- LLM cache cleanup (noted for future)

## Owned Files Or Modules

New files:

- `src/resemantica/glossary/segmenter.py`
- `src/resemantica/glossary/candidate_gen.py`
- `src/resemantica/glossary/corpus_stats.py`
- `src/resemantica/glossary/evaluator.py`
- `src/resemantica/glossary/data/common_words.txt`
- `src/resemantica/glossary/data/webnovel_dict.txt`
- `src/resemantica/glossary/data/surnames.txt`
- `src/resemantica/llm/prompts/glossary_evaluate.txt`
- `tests/glossary/test_segmenter.py`
- `tests/glossary/test_candidate_gen.py`
- `tests/glossary/test_corpus_stats.py`
- `tests/glossary/test_evaluator.py`
- `tests/glossary/test_critic_dedup.py`
- `tests/glossary/test_validators_expanded.py`

Modified files:

- `src/resemantica/glossary/discovery.py` — major rewrite
- `src/resemantica/glossary/critic.py` — major rewrite (common-word critic → dedup/cluster)
- `src/resemantica/glossary/validators.py` — expand `apply_deterministic_filter()`
- `src/resemantica/glossary/models.py` — extend `GlossaryCandidate`, add `CandidateStatus` values
- `src/resemantica/glossary/pipeline.py` — rewire `discover_glossary_candidates()`
- `src/resemantica/db/glossary_repo.py` — new columns in upsert/read, alias cluster repo
- `src/resemantica/db/sqlite.py` — schema evolution (ALTER TABLE + new table)
- `src/resemantica/settings.py` — add `GlossaryConfig`
- `src/resemantica/cli.py` — new CLI flags for glossary-discover
- `src/resemantica/orchestration/runner.py` — pass updated params
- `pyproject.toml` — add `hanlp[full]` optional dependency

## Interfaces To Satisfy

- LLD: `../20-lld/lld-39-deterministic-glossary-discovery.md`
- `discover_glossary_candidates()` pipeline function: same external signature
- `GlossaryCandidate` dataclass: backward-compatible extension (new nullable fields)
- SQLite schema: backward-compatible (ALTER TABLE ADD COLUMN, new table)
- CLI: `rsem preprocess glossary-discover` — same command, new optional flags
- Translate/promote/review stages: zero changes, consume same `GlossaryCandidate` objects

## Execution Checklist

### Phase 1: Foundation (no behavior change)

- [x] **1.1** Add `hanlp[full]>=2.1` to `pyproject.toml` optional-dependencies `nlp` group
- [x] **1.2** Add `[glossary]` config section to `settings.py` (`GlossaryConfig` dataclass)
- [x] **1.3** Add config parsing in `load_config()` and validation in `validate_config()`
- [x] **1.4** Extend `GlossaryCandidate` model with new nullable fields
- [x] **1.5** Add `CandidateStatus` values: `llm_rejected`, `alias_merged`
- [x] **1.6** Schema evolution: ALTER TABLE for new columns + new `glossary_alias_clusters` table
- [x] **1.7** Update `glossary_repo.py`: `_candidate_from_row()` handles new nullable columns
- [x] **1.8** Update `glossary_repo.py`: `upsert_discovered_candidates()` includes new columns
- [x] **1.9** Verify: existing tests still pass (`uv run pytest tests/glossary/ -v`)
- [x] **1.10** Verify: `ruff check` + `mypy` clean

### Phase 2: Data Files

- [x] **2.1** Create `glossary/data/` package directory with `__init__.py`
- [x] **2.2** Create `glossary/data/common_words.txt` — curate ~5000 high-frequency common Chinese words
- [x] **2.3** Create `glossary/data/webnovel_dict.txt` — seed with ~500 common xianxia/wuxia terms
- [x] **2.4** Create `glossary/data/surnames.txt` — Chinese surnames from 百家姓
- [x] **2.5** Add data file loader utility in `glossary/data/__init__.py`

### Phase 3: HanLP Integration

- [x] **3.1** Create `glossary/segmenter.py` with `SegmentedToken` and `segment_chapter()`
- [x] **3.2** Implement lazy HanLP pipeline loading with module-level cache
- [x] **3.3** Implement graceful fallback when HanLP is not installed
- [x] **3.4** Create `tests/glossary/test_segmenter.py` — mock HanLP, verify token structure
- [x] **3.5** Verify: `ruff check` + `mypy` clean

### Phase 4: Candidate Generation

- [x] **4.1** Create `glossary/candidate_gen.py` with `RawCandidate` dataclass
- [x] **4.2** Implement NER-based extraction strategy (PERSON→character, LOC→location, ORG→faction)
- [x] **4.3** Implement POS-based noun phrase extraction (NR/NNP sequences)
- [x] **4.4** Implement suffix/prefix pattern heuristics (surnames, faction/location/technique suffixes)
- [x] **4.5** Implement webnovel dictionary lookup strategy
- [x] **4.6** Implement n-gram frequency extraction (2-6 chars, min frequency threshold)
- [x] **4.7** Implement cross-strategy deduplication (merge same normalized form)
- [x] **4.8** Create `tests/glossary/test_candidate_gen.py` — test each strategy with fixture text
- [x] **4.9** Verify: `ruff check` + `mypy` clean

### Phase 5: Corpus Statistics

- [x] **5.1** Create `glossary/corpus_stats.py` with `CorpusStats` and `ScoredCandidate`
- [x] **5.2** Implement `compute_corpus_stats()` — aggregate per-chapter counts
- [x] **5.3** Implement TF-IDF computation
- [x] **5.4** Implement C-value computation for multi-word terms
- [x] **5.5** Implement composite score formula (weighted combination)
- [x] **5.6** Create `tests/glossary/test_corpus_stats.py` — verify with known input/output
- [x] **5.7** Verify: `ruff check` + `mypy` clean

### Phase 6: Expanded Prefilter

- [x] **6.1** Add min/max length filter to `apply_deterministic_filter()`
- [x] **6.2** Add punctuation/noise filter
- [x] **6.3** Add common-word dictionary filter (load `common_words.txt`)
- [x] **6.4** Add POS-based generic rejection (pure verb/adverb/prep sequences)
- [x] **6.5** Add score threshold filter (configurable `min_corpus_score`)
- [x] **6.6** Create `tests/glossary/test_validators_expanded.py` — test each new rule
- [x] **6.7** Verify: existing validator tests still pass
- [x] **6.8** Verify: `ruff check` + `mypy` clean

### Phase 7: LLM Batch Evaluator

- [x] **7.1** Create `llm/prompts/glossary_evaluate.txt` prompt template
- [x] **7.2** Create `glossary/evaluator.py` with `EvalResult` and `evaluate_candidate_batch()`
- [x] **7.3** Implement batch construction (group candidates, render JSON, respect context budget)
- [x] **7.4** Implement LLM response parsing with JSON error handling
- [x] **7.5** Implement per-batch caching (keyed on batch content hash + prompt version)
- [x] **7.6** Create `tests/glossary/test_evaluator.py` — mock LLM, verify batch + parse
- [x] **7.7** Verify: `ruff check` + `mypy` clean

### Phase 8: Embedding Dedup / Alias Clustering

- [x] **8.1** Rewrite `glossary/critic.py` — replace common-word critic with `deduplicate_and_cluster()`
- [x] **8.2** Implement `AliasCluster` dataclass
- [x] **8.3** Implement candidate embedding via `sentence-transformers` (use `embedding_name` from config)
- [x] **8.4** Implement pairwise similarity + Union-Find clustering
- [x] **8.5** Implement canonical selection (highest composite_score in cluster)
- [x] **8.6** Implement comparison against existing locked glossary entries
- [x] **8.7** Add `upsert_alias_clusters()` and `list_alias_clusters()` to `glossary_repo.py`
- [x] **8.8** Create `tests/glossary/test_critic_dedup.py` — mock embeddings, verify clustering
- [x] **8.9** Verify: `ruff check` + `mypy` clean

### Phase 9: Pipeline Integration

- [x] **9.1** Rewrite `glossary/discovery.py` — replace LLM-driven loop with deterministic pipeline
- [x] **9.2** Update `glossary/pipeline.py:discover_glossary_candidates()` — wire all 5 stages
- [x] **9.3** Update `orchestration/runner.py` — pass correct params for new pipeline
- [x] **9.4** Update `cli.py` — add `--eval-batch-size`, `--skip-llm-eval`, `--dedup-threshold` flags
- [x] **9.5** Update integration test `tests/glossary/test_glossary_pipeline.py` — mock HanLP + LLM
- [x] **9.6** Full regression: `uv run pytest tests/ -v`
- [x] **9.7** Verify: `ruff check src/ tests/` clean
- [x] **9.8** Verify: `mypy src/resemantica/` clean

### Phase 10: Validation

- [x] **10.1** Run new pipeline on 5-10 pilot chapters, compare candidate sets vs old LLM-only
- [x] **10.2** Verify downstream compatibility: glossary-translate, glossary-promote, glossary-review work with new candidates
- [x] **10.3** Verify `--skip-llm-eval` flag produces candidates without LLM dependency
- [x] **10.4** Update `docs/20-lld/lld-03-glossary.md` with note pointing to `lld-39`

## Tests Or Smoke Checks

Unit tests:

- Each extraction strategy in `candidate_gen.py` correctly identifies known terms in fixture text
- TF-IDF and C-value produce expected scores for controlled corpus
- Each new filter rule in `validators.py` rejects/accepts correctly
- LLM evaluator constructs valid batch prompts and parses JSON responses
- Dedup clustering merges known variants and preserves distinct terms
- Schema migration adds columns without data loss

Integration tests:

- Full pipeline (mocked HanLP + mocked LLM) produces valid `GlossaryCandidate` objects
- Translate/promote/review stages accept candidates from new pipeline unchanged
- `--skip-llm-eval` flag produces candidates without LLM calls

Smoke checks:

```bash
uv run pytest tests/glossary/ -v
uv run pytest tests/ -v
uv run ruff check src/resemantica/ tests/
uv run mypy src/resemantica/
rsem preprocess glossary-discover --release test --start 1 --end 5
rsem preprocess glossary-discover --release test --start 1 --end 5 --skip-llm-eval
```

## Done Criteria

- [x] `glossary/discovery.py` no longer makes LLM calls for candidate generation
- [x] HanLP segmentation produces POS + NER annotations per chapter
- [x] 5 extraction strategies produce candidates deterministically
- [x] TF-IDF / C-value / composite scoring ranks candidates by salience
- [x] Expanded prefilter catches noise that previously required LLM or embedding critic
- [x] LLM batch evaluator provides keep/reject verdicts with reason codes
- [x] Embedding dedup clusters segmentation variants and aliases
- [x] All new columns present in `glossary_candidates` schema
- [x] `glossary_alias_clusters` table created and populated
- [x] Existing translate/promote/review pipeline works unchanged
- [x] All tests pass, `ruff check` clean, `mypy` clean
- [x] LLD-39 doc written and cross-referenced from task
