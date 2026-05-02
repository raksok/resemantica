# Task 32: Idiom Meaning Translation (`meaning_en`)

## Goal

Add a second translator-model call per idiom candidate to translate `meaning_zh` (Chinese explanation) into `meaning_en` (English explanation), stored in a new column, so the English meaning is available for future downstream use without polluting the translator's idiom rendering.

## Scope

In:

- Modify `idiom_translate.txt` prompt: remove `MEANING (ZH)` context, keep only `EVIDENCE` as context before the translate instruction.
- Create `idiom_meaning.txt` prompt: one-line translate instruction for `MEANING_ZH`.
- Add `meaning_en TEXT` column to `idiom_candidates` and `idiom_policies` tables.
- Add `meaning_en` field to `IdiomCandidate` and `IdiomPolicy` dataclasses.
- Update `idiom_repo.py`: all SQL SELECT/INSERT/UPDATE and dataclass construction to include `meaning_en`. `save_idiom_translation()` receives and stores `meaning_en`.
- Update `idiom/extractor.py`: insert detected candidates with `meaning_en=""`.
- Update `idioms/pipeline.py`: `translate_idiom_candidates()` makes two LLM calls per candidate (rendering + meaning). Promotion copies `meaning_en` to `idiom_policies`.
- Update `idioms/validators.py`: merge `meaning_en` during dedup promotion.
- Do **not** add `meaning_en` to `_hash_idiom_policies()` — not consumed downstream yet; no unnecessary cache invalidation.
- Update existing tests that construct `IdiomCandidate`/`IdiomPolicy` to include `meaning_en`.

Out:

- Adding `meaning_en` to packet bundles or translation context — consumed in a future task.
- Changing `_hash_idiom_policies()` to include `meaning_en`.
- Any TUI or CLI display of `meaning_en`.

## Owned Files Or Modules

- `src/resemantica/llm/prompts/idiom_translate.txt`
- `src/resemantica/llm/prompts/idiom_meaning.txt` (new)
- `src/resemantica/idioms/models.py`
- `src/resemantica/db/sqlite.py` (`ensure_full_schema()`)
- `src/resemantica/db/idiom_repo.py`
- `src/resemantica/idioms/extractor.py`
- `src/resemantica/idioms/pipeline.py`
- `src/resemantica/idioms/validators.py`
- `tests/idioms/` (update existing tests)

## Interfaces To Satisfy

### `save_idiom_translation()`

```python
def save_idiom_translation(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    translation_run_id: str,
    target_term: str,
    meaning_en: str,
    translator_model_name: str,
    translator_prompt_version: str,
) -> None:
```

### `IdiomCandidate` / `IdiomPolicy`

```python
@dataclass(slots=True)
class IdiomCandidate:
    ...
    meaning_en: str = ""

@dataclass(slots=True)
class IdiomPolicy:
    ...
    meaning_en: str = ""
```

### `translate_idiom_candidates()` — updated flow

```python
# Per candidate:
rendering_prompt = {SOURCE_TEXT, EVIDENCE_SNIPPET}  → translator → preferred_rendering_en
meaning_prompt  = {MEANING_ZH}                       → translator → meaning_en
save_idiom_translation(candidate_id, target_term=rendering, meaning_en=meaning, ...)
```

## Tests Or Smoke Checks

- Existing idiom pipeline tests pass with the new `meaning_en` field.
- New `meaning_en` column is populated in DB after translation phase.
- `idiom_policies` contains `meaning_en` after promotion.
- Run `uv run pytest tests/idioms`.
- Run `uv run ruff check src tests`.

## Done Criteria

- `idiom_translate.txt` updated to version 1.1 (MEANING_ZH removed, EVIDENCE-only context).
- `idiom_meaning.txt` created with the zh→en translate instruction.
- `meaning_en` column exists in both `idiom_candidates` and `idiom_policies` tables.
- `translate_idiom_candidates()` makes two translator calls per candidate and stores both `preferred_rendering_en` and `meaning_en`.
- Promotion copies `meaning_en` to `idiom_policies`.
- Existing tests pass.
