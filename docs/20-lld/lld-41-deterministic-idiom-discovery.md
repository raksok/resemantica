# LLD 41: Deterministic Idiom Discovery

## Summary

The current idiom pipeline asks the analyst model to scan raw chapter text and emit idiom candidates. This makes misses unrecoverable, costs one or more LLM calls per chapter, and keeps discovery nondeterministic. This LLD replaces that path with deterministic candidate generation, deterministic filtering, LLM batch validation, and embedding-based consistency checks. The existing translation, review, promotion, and exact-match policy consumption remain stable.

Chosen policy: no old full-chapter LLM discovery fallback. The LLM validates deterministic candidates only.

## Target Flow

```
[Idiom candidate generation]
  lexicon exact match
  HanLP segmentation + POS signals
  four-character expression mining
  fixed-pattern phrase mining
  PMI / C-value phrase detection
  repeated non-compositional phrase detection
        ↓
[Idiom feature store]
  surface form, normalized form, dictionary match
  frequency, chapter coverage, first occurrence
  representative context snippets
  literal meaning, idiomatic meaning if known
  source strategies
        ↓
[Deterministic prefilter]
  remove ordinary four-character noun phrases
  remove names, titles, locations, techniques
  reject compositional phrases unless context suggests idiomatic use
  score threshold
        ↓
[LLM batch evaluator]
  idiom/fixed expression verdict
  literal vs idiomatic usage
  literal/idiomatic/preserve translation strategy
  reason code, confidence, schema JSON
        ↓
[Embedding idiom clustering / consistency]
  cluster variant forms
  compare against approved idiom policies
  retrieve previous translations
  enforce rendering consistency
        ↓
[Existing translation/review/promotion]
```

## Public Interfaces

Preserved:

- `preprocess_idioms(...)`
- `extract_idioms(...)`
- `translate_idiom_candidates(...)`
- `review_idiom_candidates(...)`
- `promote_idiom_candidates(...)`
- `resolve_idiom_policy(...)`
- CLI: `preprocess idioms`, `idiom-review`, `idiom-promote`

Optional non-breaking additions:

- `preprocess_idioms(eval_batch_size=None, skip_llm_eval=False, dedup_threshold=None, score_threshold=None, ...)`
- matching CLI flags on `preprocess idioms`

## Data Model

Append nullable fields to `IdiomCandidate` and `idiom_candidates`:

- `dictionary_match: int | None`
- `source_strategies: str | None` — JSON list or comma-separated strategy names
- `chapter_coverage: int | None`
- `corpus_score: float | None`
- `context_snippets: str | None` — JSON list
- `literal_meaning_zh: str | None`
- `idiomatic_meaning_zh: str | None`
- `llm_is_idiom: int | None`
- `llm_usage_type: str | None` — `literal`, `idiomatic`, `mixed`, `unknown`
- `llm_translation_strategy: str | None` — `literal`, `idiomatic`, `preserve`
- `llm_reason_code: str | None`
- `llm_confidence: float | None`
- `cluster_id: str | None`
- `canonical_source_text: str | None`
- `existing_policy_id: str | None`

Do not change required `IdiomPolicy` fields in this slice. Variant consistency is applied before promotion by copying a known preferred rendering or by translating only the canonical cluster candidate and propagating that rendering to variants.

## Modules

### Shared Segmenter

Move the implementation currently in `glossary/segmenter.py` to a shared module:

- `resemantica.nlp.segmenter`

Keep `resemantica.glossary.segmenter` as a compatibility re-export. Idiom candidate generation imports the shared segmenter directly.

### Candidate Generation

New `idioms/candidate_gen.py`:

- `RawIdiomCandidate`: surface form, normalized form, source strategies, POS tags, dictionary match, meanings, appearances, snippets, first/last chapter.
- `generate_chapter_idiom_candidates(chapter_number, source_text, tokens=None)`.
- `merge_across_chapters(accumulator, chapter_candidates)`.

Strategies:

- lexicon exact match from `idioms/data/idiom_lexicon.tsv`
- four-character CJK windows with reduplication / antithesis / classical-function-word signals
- POS pattern extraction for likely set phrases
- fixed phrase regexes such as `一...就...`, `不...不...`, `又...又...`, `非...不可`
- repeated phrase candidates for terms recurring across chapters

### Corpus Scoring

New `idioms/corpus_stats.py`:

- compute frequency, document frequency, PMI-like association, C-value, and composite score.
- keep formulas simple and deterministic; exact values are less important than stable ranking.

### Prefilter

Extend `idioms/validators.py` with `apply_deterministic_filter(candidates, config, known_glossary_terms=None)`.

Filter reasons:

- `ordinary_noun_phrase`
- `proper_name_or_title`
- `location_or_technique`
- `compositional_phrase`
- `low_score`
- `too_short`
- `too_long`

Candidates with lexicon matches bypass the score threshold unless they are clearly malformed.

### LLM Evaluator

New `idioms/evaluator.py` and `llm/prompts/idiom_evaluate.txt`.

The evaluator prompt is analyst-facing and returns compact JSON only. It forbids markdown, prose, explanations, analysis, chain-of-thought, and `<think>` artifacts. Idiom translation and meaning prompts were intentionally excluded from this deterministic-discovery optimization pass; later tasks may own non-HY-MT translator prompts separately as long as their output contracts remain stable.

Response schema per item:

```json
{
  "candidate_id": "ican_...",
  "is_idiom": true,
  "usage_type": "idiomatic",
  "translation_strategy": "idiomatic",
  "reason_code": "lexicon_match",
  "confidence": 0.94,
  "meaning_zh": "一举两得"
}
```

Allowed reason codes include:

- `lexicon_match`
- `chengyu_pattern`
- `fixed_expression`
- `repeated_non_compositional`
- `ordinary_noun_phrase`
- `proper_name`
- `compositional`
- `insufficient_evidence`
- `eval_error`

Malformed or missing rows default to rejection with `reason_code="eval_error"`.

### Clustering

New `idioms/critic.py`:

- embed `"{surface} {meaning_zh} {context}"` using `config.models.embedding_name`
- cluster above `dedup_similarity_threshold`
- compare canonical cluster terms to existing `IdiomPolicy` rows
- if a known policy match is found, set candidate rendering/meaning from that policy and mark it ready for promotion
- gracefully return unchanged candidates if `sentence-transformers` is unavailable

## Pipeline Integration

`extract_idioms()` keeps its name and return type but changes behavior:

1. collect chapter text as today
2. generate deterministic candidates per chapter
3. merge and score across selected chapters
4. convert survivors to `IdiomCandidate`
5. run prefilter
6. optionally run LLM evaluator on unfiltered candidates
7. cluster and apply consistency metadata
8. return candidates to existing repository upsert

`preprocess_idioms()` remains the owner of database upsert, translation, promotion, snapshots, and events. Existing `chapter_started`, `chapter_completed`, and `chapter_skipped` events remain, with candidate counts derived from deterministic output.

## Backward Compatibility

- New SQLite columns are nullable and added through `ensure_schema()` evolution.
- Existing idiom rows without metadata continue to deserialize.
- Review files remain schema version 1.
- Packet builder continues reading only approved `IdiomPolicy` rows.
- `idiom_detect.txt` can remain in the prompt directory for historical compatibility but is not used by the normal discovery path.

## Tests

- `tests/idioms/test_candidate_gen.py`
- `tests/idioms/test_evaluator.py`
- `tests/idioms/test_critic.py`
- expanded `tests/idioms/test_idiom_pipeline.py`

Validation:

```bash
uv run --extra dev pytest tests/idioms -q
uv run --extra dev pytest tests/glossary tests/packets tests/cli -q
uv run --extra dev ruff check src/resemantica tests
uv run --extra dev mypy src/resemantica
```

## Out Of Scope

- replacing exact-match runtime idiom lookup with fuzzy matching
- large production lexicon curation
- using graph storage for idiom policies
- changing packet hash fields beyond existing idiom policy content

---

## Post-MVP Improvements

The following improvements were added after the initial deterministic discovery implementation. They address crash resilience, production safety for 1000+ chapter runs, and candidate quality.

### P0 — Crash Resilience

#### Summary Table Error Handling

The `summary_drafts` query in `preprocess_idioms()` is wrapped in `try/except` so the pipeline doesn't crash when run before summaries (graceful degradation, same as glossary pipeline).

#### Checkpoint/Resume

New `idiom_checkpoints` table and `set_checkpoint/get_checkpoint` repo functions, matching the glossary checkpoint pattern. `preprocess_idioms()` accepts a `resume: bool = False` parameter. On resume, the detect and translate phases are skipped if their stage name checkpoint exists.

### P1 — Summary Cross-Referencing

`extract_idioms()` now loads `chapter_summaries` from `summary_drafts.content_json` (same query as glossary). Summary `new_terms` are cross-referenced against idiom candidates. Idioms appearing in `new_terms` get a `"from_summary"` strategy, contributing to `strategy_count` in scoring, and a 1.15× score multiplier.

### P2 — LLM Eval Persistence (persist_callback)

`evaluate_idiom_candidate_batch()` accepts a `persist_callback` parameter. In `extract_idioms()`, candidates are upserted to DB before LLM eval (matching glossary's flow), and the callback writes `llm_is_idiom` fields per-batch. Crash during eval loses at most one batch instead of all batches.

### P3 — Scoring Improvements

Scoring formula upgraded from `0.45*dict + 0.3*strategy + 0.25*frequency` to:

```
composite = 0.35*dict + 0.25*strategy + 0.20*frequency + 0.20*c_value_norm
```

Where `c_value_norm = c_value / max_c_value`. Strategy-specific multipliers applied: 1.15× for lexicon matches, 1.1× for four-char with dictionary match, 0.9× for fixed-pattern only.

### P3 — Pre-Filter Improvements

Added to `apply_deterministic_filter()`:
- Common-word stoplist matching glossary's `_COMMON_STOPLIST`
- Punctuation noise rejection

### Files Modified

| File | Change |
|---|---|
| `db/sqlite.py` | New `idiom_checkpoints` table |
| `db/idiom_repo.py` | `set_checkpoint()`, `get_checkpoint()` |
| `idioms/pipeline.py` | try/except on summary query, `resume` param, checkpoint calls, load `chapter_summaries` |
| `idioms/extractor.py` | Accept `chapter_summaries`, build `summary_term_set`, upsert before eval, `persist_callback` |
| `idioms/candidate_gen.py` | Accept `summary_data`, cross-ref `new_terms` |
| `idioms/corpus_stats.py` | Accept `summary_term_set`, 1.15× boost, C-value in composite, strategy multipliers |
| `idioms/evaluator.py` | Accept `persist_callback` parameter |
| `idioms/validators.py` | Common-word stoplist, punctuation noise filter |
