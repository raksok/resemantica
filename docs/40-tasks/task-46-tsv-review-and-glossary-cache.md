# Task 46: TSV Review + Glossary-Aware Translation Cache

## Milestone
M46

## Depends On
M3 (Canonical Glossary), M42 (Multi-Model Preprocess Translation), M8 (Chapter Packets)

## Goal

Replace JSON-only glossary review with a TSV format that opens in Excel, and make translation checkpoints aware of upstream changes so glossary edits automatically trigger re-translation.

## Scope

In:

- TSV output from `glossary-review` alongside existing JSON
- TSV input for `glossary-promote --review-file`
- `packet_version_hash` column in `translation_checkpoints` table
- Translation checkpoint lookup/storage includes packet hash
- Pass 1, 2, and 3 all check packet hash before cache hit
- Updated docs (LLD + task brief)
- Tests for TSV round-trip and cache invalidation

Out:

- Idiom review file (separate task if needed)
- TUI integration for review (separate task)
- Fuzzy glossary matching

## Owned Files Or Modules

- `src/resemantica/glossary/pipeline.py`
- `src/resemantica/cli.py`
- `src/resemantica/db/sqlite.py`
- `src/resemantica/translation/checkpoints.py`
- `src/resemantica/translation/pipeline.py`
- `tests/glossary/test_glossary_pipeline.py`
- `tests/translation/test_translate_chapter.py`
- `tests/translation/test_checkpoints.py` (new)
- `docs/20-lld/lld-46-tsv-review-and-glossary-cache.md`
- `docs/40-tasks/task-46-tsv-review-and-glossary-cache.md`

## Interfaces To Satisfy

- `rsem preprocess glossary-review` writes `review.tsv` in addition to `review.json`
- `rsem preprocess glossary-promote -F review.tsv` applies user edits
- `rsem preprocess glossary-promote -F review.json` still works (backward compat)
- Changing locked glossary → re-run production → chapters auto-re-translate

## Tests Or Smoke Checks

### Phase 1 (TSV)
- `test_review_tsv_written` — TSV file exists with correct header and row count
- `test_review_tsv_matches_json` — TSV content matches JSON entries
- `test_promote_with_tsv_override` — override translation via TSV, verify promotion
- `test_promote_tsv_delete` — delete action via TSV, entry not promoted
- `test_promote_tsv_add` — add action via TSV, new entry created and promoted
- `test_promote_tsv_mixed_actions` — mix of keep/delete/add in one file
- `test_promote_tsv_bad_header` — invalid header raises clear error
- `test_promote_tsv_empty` — header-only TSV is no-op
- `test_promote_json_still_works` — existing JSON review file still works

### Phase 2 (Cache)
- `test_checkpoint_hash_mismatch_triggers_retranslate` — change glossary → new packet_hash → cache miss
- `test_checkpoint_hash_matches_skips` — same packet_hash → cache hit
- `test_checkpoint_old_row_mismatch` — old row without hash → cache miss
- `test_checkpoint_pass3_also_checks_hash` — pass3 also invalidates on hash change
- `test_save_and_load_with_hash` — checkpoint round-trip with hash
- `test_load_with_wrong_hash` — mismatched hash returns None
- `test_load_with_empty_hash` — empty hash doesn't match stored hash

## Done Criteria

- [ ] `glossary-review` produces valid `review.tsv` that opens in Excel
- [ ] `glossary-promote -F review.tsv` applies keep/delete/add correctly
- [ ] `glossary-promote -F review.json` still works unchanged
- [ ] Glossary edit → re-run production → chapters auto-re-translate
- [ ] No glossary change → re-run production → chapters skip from cache
- [ ] `ruff check` passes
- [ ] `mypy` passes
- [ ] All new tests pass
- [ ] LLD updated
