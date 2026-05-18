# LLD 54: Summary Schema Recovery

## Summary

Chinese structured-summary generation now has a narrow recovery path for repeated small-model schema drift. Recovery runs only inside `summaries.generator.generate_chapter_summary()` after JSON parsing, chapter identity normalization, explicit non-story handling, deterministic validation, and one targeted retry for the same recoverable class.

## Recovery Policy

Recoverable classes:

- Missing `is_story_chapter`: inject `true` and emit `missing_is_story_chapter_defaulted_true`.
- Malformed `relationships_changed` entries inside an otherwise valid list: drop invalid entries and emit `invalid_relationships_changed_entries_dropped`.
- Empty or non-string `setting` or `tone`: set affected fields to `"未明确"` and emit `empty_setting_or_tone_defaulted`.

Hard failures remain hard:

- JSON parse errors after retries.
- Future-knowledge errors.
- Chapter identity conflicts.
- Missing or invalid `narrative_progression`.
- Invalid list fields such as `relationships_changed` not being a list.
- Any mixed validation result that contains unrecoverable errors.

## Flow

1. Generate and parse one structured JSON object.
2. Normalize chapter identity warnings against the canonical pipeline chapter number.
3. Apply explicit non-story behavior before schema validation.
4. Validate with `validate_chinese_summary()`.
5. If validation fails with a recoverable class that has not yet retried, retry with compact field-specific feedback.
6. If the same recoverable class fails again and no unrecoverable errors remain, apply deterministic recovery and validate again.
7. Persist only validated structured summaries; persist recovery warning codes in the chapter artifact `warnings` list.

## Prompt Contract

`summary_zh_structured.txt` is versioned at `1.5`. It is schema-first for 4B-9B analyst models:

- Compact directives.
- Required-key checklist.
- Literal JSON skeleton.
- Explicit JSON boolean guidance for `is_story_chapter`.
- Object-only `relationships_changed` examples.
- Short retry feedback that does not echo invalid model output.

## Tests

- Retry and recovery for missing `is_story_chapter`.
- Retry and malformed-entry dropping for `relationships_changed`.
- Retry and `"未明确"` defaults for empty `setting` and `tone`.
- Mixed recoverable and unrecoverable schema failure without recovery.
- Prompt regression for checklist, boolean guidance, and relationship object examples.
