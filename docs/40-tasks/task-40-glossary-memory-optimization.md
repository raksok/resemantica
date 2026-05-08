# Task 40: Glossary Memory Optimization — Incremental Accumulation

- **Milestone:** M40
- **Depends on:** M39 (Deterministic Glossary Discovery — completed)
- **Status:** Active

## Goal

Eliminate the `per_chapter_raw: dict[int, list[RawCandidate]]` memory accumulation in `glossary/discovery.py` that holds all 1000+ chapters' candidates simultaneously (~240 MB peak). Replace with incremental accumulation: merge candidates and aggregate corpus statistics per-chapter in a single loop, freeing each chapter's intermediates via GC.

## Scope

In:

- New `merge_across_chapters()` helper in `candidate_gen.py` — incremental merge into a caller-owned accumulator dict
- Rewrite `discovery.py:discover_candidates_from_extracted()` — remove `per_chapter_raw`, flatten, and late-merge; replace with single-loop incremental merge + stats
- Remove unused imports (`compute_corpus_stats`, `merge_candidates` from discovery)
- Test for `merge_across_chapters()` in `test_candidate_gen.py`

Out:

- `corpus_stats.py` — untouched (existing `compute_corpus_stats()` kept for test compatibility)
- Candidate generation strategies — unchanged
- Scoring logic (`score_candidates()`) — unchanged
- `GlossaryCandidate` model — unchanged
- Pipeline entry points — unchanged
- Downstream consumers (translate/promote/review) — zero changes

## Owned Files Or Modules

Modified files:

- `src/resemantica/glossary/candidate_gen.py` — add `merge_across_chapters()`
- `src/resemantica/glossary/discovery.py` — rewrite accumulation loop
- `tests/glossary/test_candidate_gen.py` — add test for `merge_across_chapters()`

## Interfaces To Satisfy

- `discover_candidates_from_extracted()`: same signature, same output semantics (list of `GlossaryCandidate`)
- `GlossaryCandidate` objects: same fields, same values, deterministic across equivalent runs
- No schema or config changes

## Execution Checklist

### Phase 1: Helper Function

- [ ] **1.1** Add `merge_across_chapters(accumulator, chapter_candidates)` to `candidate_gen.py`
- [ ] **1.2** Logic: identical to `merge_candidates()` inner loop but operates on caller-owned dict
- [ ] **1.3** Design: pure function, returns the accumulator dict for convenience

### Phase 2: Discovery Rewrite

- [ ] **2.1** Remove `per_chapter_raw` dict from `discover_candidates_from_extracted()`
- [ ] **2.2** Replace with `merged_accumulator: dict[str, RawCandidate]` and per-chapter merge via `merge_across_chapters()`
- [ ] **2.3** Replace `compute_corpus_stats()` call with inline `term_freq`/`doc_freq`/`total_chapters` accumulation in the loop
- [ ] **2.4** Build `CorpusStats` object after the loop for `score_candidates()`
- [ ] **2.5** Replace late `merge_candidates(all_raw_list)` with `list(merged_accumulator.values())`
- [ ] **2.6** Update imports: remove `compute_corpus_stats`, `merge_candidates`; add `merge_across_chapters`, `CorpusStats`

### Phase 3: Test

- [ ] **3.1** Add `test_merge_across_chapters()` to `test_candidate_gen.py`
- [ ] **3.2** Test: 2-3 chapters of candidates, verify incremental produces same output as batch `merge_candidates()`
- [ ] **3.3** Test: empty list, single candidate, duplicate across chapters
- [ ] **3.4** Verify: `uv run pytest tests/glossary/ -v`

### Phase 4: Validation

- [ ] **4.1** Full regression: `uv run pytest tests/ -v`
- [ ] **4.2** `ruff check src/resemantica/ tests/` clean
- [ ] **4.3** `mypy src/resemantica/` clean

## Tests Or Smoke Checks

Unit tests:

- `merge_across_chapters()` produces identical output to `merge_candidates()` for same input
- Empty candidate list: no error, returns empty dict
- Single candidate across chapters: appearances accumulate, strategies merge
- Different `type_prior` values: higher priority wins (same as `merge_candidates()`)

Integration:

```bash
uv run pytest tests/glossary/ -v
uv run pytest tests/ -v
uv run ruff check src/resemantica/ tests/
uv run mypy src/resemantica/
```

## Done Criteria

- [ ] `per_chapter_raw` eliminated from `discover_candidates_from_extracted()`
- [ ] `all_raw_list` and separate `merge_candidates()` call eliminated
- [ ] `compute_corpus_stats()` no longer called from discovery (but still exists for tests)
- [ ] Per-chapter `RawCandidate` objects freed by GC after each loop iteration
- [ ] Peak memory reduced by ~140 MB (from ~440 MB to ~280 MB for 1000 chapters)
- [ ] Same candidates, same scores, same promoted set — zero quality change
- [ ] All tests pass, `ruff check` clean, `mypy` clean
