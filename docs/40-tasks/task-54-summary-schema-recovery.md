# Task 54: Summary Schema Recovery

## Milestone

M54

## Depends On

M53

## Goal

Harden Chinese structured-summary generation against small analyst-model schema drift without accepting unsafe summaries or weakening deterministic validation.

## Scope

- Add scoped recovery in `summaries.generator.generate_chapter_summary()` for repeated recoverable schema errors.
- Keep parse failures, future knowledge, chapter identity conflicts, invalid list fields, missing or invalid `narrative_progression`, and mixed unrecoverable schema errors as hard failures.
- Rewrite `summary_zh_structured.txt` for compact schema-stable output from small analyst models and bump its prompt version.
- Persist recovery decisions as summary warnings so operators can audit any deterministic default or dropped malformed field.

## Owned Files Or Modules

- `src/resemantica/summaries/generator.py`
- `src/resemantica/llm/prompts/summary_zh_structured.txt`
- `tests/summaries/test_summary_pipeline.py`
- Summary task, LLD, and operations docs

## Interfaces To Satisfy

- Structured summary JSON schema remains unchanged.
- Explicit `is_story_chapter: false` still skips non-story chapters before story validation.
- Recoverable warnings:
  - `missing_is_story_chapter_defaulted_true`
  - `invalid_relationships_changed_entries_dropped`
  - `empty_setting_or_tone_defaulted`

## Tests Or Smoke Checks

- Retry success and default recovery for missing `is_story_chapter`.
- Retry success and malformed-entry dropping for `relationships_changed`.
- Retry success and `"未明确"` defaults for empty `setting` and `tone`.
- Mixed recoverable plus unrecoverable schema errors fail without defaults.
- Prompt regression checks cover required keys, boolean guidance, and relationship object examples.
- Focused summaries tests, affected packet/glossary tests, Ruff, and mypy pass.

## Done Criteria

- Repeated recoverable schema drift can produce a validated summary only after one targeted retry.
- Recovery is deterministic, warning-backed, and limited to known safe schema repair.
- Prompt version bump invalidates old cached structured-summary responses.
