# Task 18d: Split Idiom Detection and Translation

## Goal
Split the single-pass idiom pipeline (detect + translate in one LLM call) into two phases — Analyst detects Chinese idioms, then Translator produces English renderings — matching the glossary pattern.

## Scope

In:
- Update `idiom_detect.txt` prompt to remove `preferred_rendering_en`.
- Create `idiom_translate.txt` prompt for the Translator model.
- Update `idioms/extractor.py` `_DetectedIdiom` and `_parse_detected_idioms` to drop English rendering.
- Add `translate_idiom_candidates()` to `idioms/pipeline.py`.
- Add `save_idiom_translation()` and `list_candidates_for_translation()` to `idiom_repo.py`.
- Add tracking columns (`translation_run_id`, `translator_model_name`, `translator_prompt_version`) to `idiom_candidates` via migration `010_idiom_translate.sql`.
- Add `translation_run_id`, `translator_model_name`, `translator_prompt_version` to `IdiomCandidate` model.
- Update `list_candidates_for_promotion()` to filter on `candidate_status = 'translated'`.
- Update `preprocess_idioms()` in pipeline to run detect → translate → promote in sequence.
- Update `orchestration/runner.py` `preprocess-idioms` stage to call the pipeline as-is (no CLI change).
- Update test mocks to handle two prompt types.

Out:
- Adding `translation_explanation` or similar explanatory fields (scrapped for simplicity).
- Changing `IdiomPolicy` or `IdiomConflict` models.
- Changing the CLI command structure (`preprocess idioms` stays single).
- Changing the `STAGE_ORDER` or orchestration flow.

## Owned Files Or Modules
- `src/resemantica/llm/prompts/idiom_detect.txt`
- `src/resemantica/llm/prompts/idiom_translate.txt` (new)
- `src/resemantica/idioms/extractor.py`
- `src/resemantica/idioms/pipeline.py`
- `src/resemantica/idioms/models.py`
- `src/resemantica/db/idiom_repo.py`
- `src/resemantica/db/migrations/010_idiom_translate.sql` (new)
- `src/resemantica/orchestration/runner.py`
- `tests/idioms/test_idiom_pipeline.py`

## Interfaces To Satisfy
- `idiom_detect.txt` output schema drops `preferred_rendering_en`.
- `idiom_translate.txt` returns plain text English rendering.
- `idiom_repo.list_candidates_for_translation(conn, release_id) -> list[IdiomCandidate]`
- `idiom_repo.save_idiom_translation(conn, *, candidate_id, translation_run_id, target_term, translator_model_name, translator_prompt_version) -> None`
- `list_candidates_for_promotion()` only returns candidates with `candidate_status = 'translated'`.
- `preprocess_idioms()` return dict gains `translated_count` field.

## Tests Or Smoke Checks
- **Unit:** Mock detection returns idiom without English → verify candidate has `preferred_rendering_en=""`.
- **Unit:** Mock translation returns English → verify `save_idiom_translation` fills the field.
- **Integration:** Run full `preprocess_idioms` with mocked detection + translation → verify policy has correct English rendering.
- **Regression:** Existing promotion/conflict tests still pass.

## Done Criteria
- `idiom_detect.txt` no longer asks for `preferred_rendering_en`.
- `idiom_translate.txt` exists and is wired into the pipeline.
- Detection produces candidates with `preferred_rendering_en=""`, `candidate_status="discovered"`.
- Translation phase fills `preferred_rendering_en`, sets `candidate_status="translated"`.
- Promotion only promotes `translated` candidates.
- Migration `010_idiom_translate.sql` adds tracking columns.
- All 159+ tests pass.
