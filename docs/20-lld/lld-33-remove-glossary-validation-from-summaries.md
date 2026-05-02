# LLD 33: Remove Glossary Conflict Check from Summary Validation

## Summary

Remove the `_validate_glossary_terms()` function from the summary validation pipeline. The locked glossary was designed to enforce translation consistency in output text, but summaries inherently need to refer to characters, locations, and other entities by name — causing a high rate of false-positive `generation_failed` rejections. The glossary check is eliminated entirely from the summary validation path.

## Problem Statement

### Current Behavior

`validate_chinese_summary()` in `summaries/validators.py` runs three checks:

1. **`_validate_schema()`** — structural field presence and types
2. **`_validate_future_knowledge()`** — no references to chapters beyond the current one
3. **`_validate_glossary_terms()`** — no locked glossary target term appears in any summary text field

### Observed Failure

Chapter 13 (release `plt001`) generated structurally valid JSON but was rejected because 6 locked glossary target terms appeared naturally in the summary:

| Target Term | Category | Source |
|---|---|---|
| `Chen Ping'an` | character | Key events, narrative progression |
| `Song Jixin` | character | Key events |
| `Zhi Gui` | character | Key events |
| `Grandpa Wu` | character | Key events |
| `Niping Alley` | location | Key events |
| `Old Yao` | character | Key events |

Every chapter summary that mentions characters or locations from the locked glossary will fail this check. The glossary conflict check is designed for **translation output** where locked terms should be consistently rendered, not for **summaries** where referring to entities by their established names is correct and necessary.

### Root Cause

`_validate_glossary_terms()` at `validators.py:139-155`:

```python
def _validate_glossary_terms(
    summary: dict[str, object],
    *,
    locked_glossary: list[LockedGlossaryEntry],
) -> list[str]:
    errors: list[str] = []
    combined_text = "\n".join(_collect_text_fields(summary))
    normalized_text = combined_text.casefold()
    for entry in locked_glossary:
        target = entry.target_term.strip()
        if not target:
            continue
        if target.casefold() in normalized_text:
            errors.append(
                f"glossary_conflict: Chinese summary contains locked glossary target term {target!r}"
            )
    return errors
```

It casefold-matches every locked target term against every string field in the summary, including `characters_mentioned`, `key_events`, `narrative_progression`, `setting`, `tone`, and `relationships_changed` values. No category filtering exists.

This check was appropriate for **translation output** validation (where seeing a locked source term suggests inconsistent translation) but is inappropriate for **summaries** (where entities must be referenced by name).

## Design

### Approach

Remove `_validate_glossary_terms()` entirely and its call from `validate_chinese_summary()`. The other two validators (`_validate_schema`, `_validate_future_knowledge`) remain.

An intermediate approach — filtering by `character`/`location` categories — was considered but rejected because:
- `item_artifact`, `technique`, and other categories can also contain entity names that naturally appear in summaries
- The check serves no purpose for summaries since there is no translation consistency requirement
- No reliable way to distinguish "leaked untranslated term" from "correct entity name" without changing the check's semantics entirely

### Affected Files

| File | Change |
|---|---|
| `src/resemantica/summaries/validators.py` | Remove `_validate_glossary_terms()` function (lines 139-155). Remove its call (lines 172-177). Remove `locked_glossary` parameter from `validate_chinese_summary()` signature. Keep import of `LockedGlossaryEntry` — still used by `validate_chinese_summary_content()`. |
| `src/resemantica/summaries/generator.py` | Remove `locked_glossary=locked_glossary,` from the `validate_chinese_summary()` call (line 280). |
| `tests/summaries/test_summary_pipeline.py` | Remove `locked_glossary=[],` from the `validate_chinese_summary()` call (line 599). |

### Unchanged

- `pipeline.py` — still fetches `locked_glossary` via `list_locked_entries()` and passes it to `generate_chapter_summary()` for prompt rendering
- `generator.py:103` — still passes `locked_glossary` to `_generate_structured_summary()` for `LOCKED_GLOSSARY` section in prompts
- `validate_chinese_summary_content()` — still uses `locked_glossary` for `_format_glossary_context()` in the LLM-based validation prompt
- All other glossary validation logic in `glossary/pipeline.py` and `db/glossary_repo.py`

### Data Flow

```
pipeline.py
  ├── list_locked_entries() → locked_glossary         ← still fetched
  ├── generate_chapter_summary(locked_glossary)
  │     ├── _generate_structured_summary(locked_glossary)  ← prompt rendering, still passes
  │     │     └── render LOCKED_GLOSSARY section
  │     └── validate_chinese_summary(locked_glossary)      ← NO LONGER USED
  │           └── _validate_glossary_terms()               ← REMOVED
  └── validate_chinese_summary_content(locked_glossary)    ← still uses it
```

## Migration

No DB migration. No schema change. This is a code-only change — removes a validation layer that was producing false positives.

## Backward Compatibility

| Scenario | Behaviour |
|---|---|
| Existing drafts with `validation_status="failed"` due to glossary conflict | They stay "failed" in DB; re-running the pipeline will re-process the chapter and succeed |
| `locked_glossary` being empty | No effect — the empty list was already handled by the removed function (`continue` on empty target) |
| Future addition of new glossary categories | No impact — glossary check is gone from summaries entirely |

## Out Of Scope

- Removing glossary conflict detection from other pipelines (translation, idiom).
- Changing `_validate_glossary_terms()` for reuse — it's deleted.
- Any schema or DB changes.
