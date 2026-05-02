# Task 33: Remove Glossary Conflict Check from Summary Validation

## Goal

Remove the `_validate_glossary_terms()` check from summary validation. The locked glossary was designed for translation output consistency, not for summaries — character names, locations, and other locked terms naturally appear in summary text and cause false-positive rejections.

## Background

A summary for chapter 13 (release `plt001`) generated perfectly valid JSON that passed all schema and future-knowledge checks, but was rejected with `validation_status="failed"`. Investigation revealed 6 locked glossary target terms (`Chen Ping'an`, `Song Jixin`, `Zhi Gui`, `Grandpa Wu`, `Niping Alley`, `Old Yao`) appeared naturally in the summary text. The glossary conflict check treats any exact match of a locked target term in any text field as a violation, which is inappropriate for summaries that must refer to characters and locations by name.

## Scope

In:

- Remove `_validate_glossary_terms()` function from `summaries/validators.py`.
- Remove the call to it inside `validate_chinese_summary()`.
- Remove the `locked_glossary` parameter from `validate_chinese_summary()` signature (the parameter is unused after the function removal).
- Update `generator.py` caller to not pass `locked_glossary` to `validate_chinese_summary()`.
- Update the test in `test_summary_pipeline.py` that calls `validate_chinese_summary()` with `locked_glossary`.

Out:

- Changing any other validator or pipeline (idiom, glossary, translation).
- Removing `locked_glossary` parameter from `validate_chinese_summary_content()` — it still uses it for `_format_glossary_context()` in the LLM-based validation prompt.
- Removing any glossary fetching or prompt-rendering logic — `locked_glossary` still flows through `pipeline.py → generator.py → _generate_structured_summary()` for prompt rendering.

## Owned Files Or Modules

- `src/resemantica/summaries/validators.py`
- `src/resemantica/summaries/generator.py`
- `tests/summaries/test_summary_pipeline.py`

## Interfaces To Satisfy

### `validate_chinese_summary()` — updated signature

```python
def validate_chinese_summary(
    *,
    structured_summary: dict[str, Any],
    expected_chapter_number: int,
) -> ValidationResult:
```

The `locked_glossary` parameter is removed. The function still validates schema and future knowledge; glossary conflict check is eliminated.

### Caller update in `generator.py`

```python
validation = validate_chinese_summary(
    structured_summary=parsed,
    expected_chapter_number=chapter_number,
)
```

## Tests Or Smoke Checks

- `test_non_story_chapter_validator_flagged` in `test_summary_pipeline.py` still calls `validate_chinese_summary()` without `locked_glossary`.
- Run `uv run pytest tests/summaries`.
- Run `uv run ruff check src tests`.

## Done Criteria

- `_validate_glossary_terms()` removed from `summaries/validators.py`.
- `validate_chinese_summary()` no longer takes `locked_glossary` parameter and no longer checks for glossary term conflicts.
- `generator.py` caller updated.
- Test updated.
- All existing tests pass.
- Lint clean.
