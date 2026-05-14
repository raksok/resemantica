# Task 44: Summary Chapter Identity Normalization

## Milestone
M44

## Depends On
M4, M20C, M43

## Goal
Prevent summary generation from failing when an EPUB spine chapter has a filename or visible source heading that suggests a different chapter number than the canonical extracted chapter number.

## Scope
- Keep OPF spine/extracted `chapter_number` as the canonical identity.
- Normalize LLM-returned summary `chapter_number` to the canonical value before schema validation.
- Record chapter identity mismatches as warnings in events and summary artifacts.
- Pass chapter identity warnings into LLM summary content validation so expected filename/heading mismatches are not re-reported as content failures.
- Preserve non-blocking LLM content-validation warnings separately from validation flags.
- Preserve strict validation for invalid JSON, missing fields, non-story chapters, and unsupported/future content unrelated to the visible source heading.

## Owned Files Or Modules
- `src/resemantica/summaries/generator.py`
- `src/resemantica/summaries/pipeline.py`
- `src/resemantica/summaries/validators.py`
- `src/resemantica/llm/prompts/summary_zh_structured.txt`
- `tests/summaries/test_summary_pipeline.py`
- `docs/20-lld/lld-44-summary-chapter-identity-normalization.md`

## Interfaces To Satisfy
- No new CLI flags.
- Summary artifacts include a `warnings` array when chapter identity mismatches are detected.
- Summary artifacts include `llm_validation_warnings` separately from `llm_validation_flags`.
- `preprocess-summaries.chapter_identity_warning` events are emitted for filename/content/LLM chapter-number mismatches.
- `preprocess-summaries.chapter_identity_warning` events include a non-empty human-readable message.
- Existing downstream consumers continue reading canonical `chapter_number` values.

## Tests Or Smoke Checks
- Regression: canonical chapter 12 with visible/source-reported chapter 4 succeeds and records warnings.
- Regression: canonical chapter 4 with visible chapter 12 does not fail future-knowledge validation when the visible source heading is referenced.
- Regression: canonical chapter 13 with visible source heading `Chapter 1` succeeds and passes identity context into LLM content validation.
- Regression: fenced JSON returned by LLM content validation parses successfully.
- Regression: LLM content-validation warnings are persisted but do not emit `llm_validation_warning` events unless they are flags.
- Existing chapter-number mismatch test is updated from hard failure to normalization warning.
- Focused summaries tests pass, followed by affected suites, Ruff, and mypy.

## Done Criteria
- Summary preprocessing succeeds for filename/content chapter-number disagreement.
- Mismatch warnings are persisted in summary artifacts and events.
- Identity-warning events have readable messages.
- Content-validator warnings are persisted separately from flags.
- Validation remains strict for unrelated future-chapter leaks.
