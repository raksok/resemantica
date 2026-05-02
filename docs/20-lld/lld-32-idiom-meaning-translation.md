# LLD 32: Idiom Meaning Translation (`meaning_en`)

## Summary

Add a second translator-model pass per idiom candidate to translate `meaning_zh` (Chinese explanation) into `meaning_en` (English explanation), stored in a new DB column and propagated through promotion to `idiom_policies`. The existing `idiom_translate.txt` prompt is cleaned up to remove `MEANING_ZH` context, keeping only `EVIDENCE` as contextual signal.

## Problem Statement

Currently the idiom pipeline:
1. **Analyst detection** produces `meaning_zh` (Chinese explanation of the idiom) and an initial `preferred_rendering_en`
2. **Translator rendering** overwrites `preferred_rendering_en` but never sees `meaning_zh` in its prompt — the current `idiom_translate.txt` prompt passes `MEANING_ZH` as input context, which dilutes the translation instruction

This means:
- The translator receives Chinese text (`meaning_zh`) as context even though it's only supposed to render the idiom — minor quality risk
- No English meaning is ever stored, so downstream stages can't reference the idiom's meaning in English
- The `MEANING_ZH` field in the translation prompt is never used by the translator output (which only produces the rendering)

Two separate changes address this:
- **Clean up** `idiom_translate.txt` to only pass `EVIDENCE` as context
- **Add** a dedicated second call to translate `meaning_zh → meaning_en`, stored separately

## Prompt Changes

### `idiom_translate.txt` (version 1.0 → 1.1)

Before:
```
MEANING (ZH): {MEANING_ZH}
EVIDENCE: {EVIDENCE_SNIPPET}

Translate the following Chinese idiom into natural English with no extra commentary.

{SOURCE_TEXT}
```

After:
```
# version: 1.1

EVIDENCE: {EVIDENCE_SNIPPET}

Use above as context, Translate the following Chinese idiom into natural English with no extra commentary.

{SOURCE_TEXT}
```

### `idiom_meaning.txt` (new, version 1.0)

```
# version: 1.0

Translate the following zh into en with no extra commentary.

{MEANING_ZH}
```

## Schema Changes

### `idiom_candidates` table

Add column after `preferred_rendering_en`:

```sql
meaning_en TEXT NOT NULL DEFAULT ''
```

### `idiom_policies` table

Same addition:

```sql
meaning_en TEXT NOT NULL DEFAULT ''
```

### `ensure_full_schema()` in `db/sqlite.py`

Both `CREATE TABLE IF NOT EXISTS` statements updated to include the new column inline.

## Dataclass Changes

### `IdiomCandidate`

```python
@dataclass(slots=True)
class IdiomCandidate:
    candidate_id: str
    ...
    meaning_en: str = ""   # NEW, default empty
```

### `IdiomPolicy`

```python
@dataclass(slots=True)
class IdiomPolicy:
    idiom_id: str
    ...
    meaning_en: str = ""   # NEW, default empty
```

Default empty string ensures backward compatibility with existing serialized data.

## Translation Flow Change

Current: `translate_idiom_candidates()` makes 1 LLM call per candidate.

New: makes 2 LLM calls per candidate:

```python
for candidate in pending:
    # Call 1: idiom rendering
    rendering = translator.generate_text(
        model_name=translator_model_name,
        prompt=render_named_sections(rendering_prompt, {
            "SOURCE_TEXT": candidate.source_text,
            "EVIDENCE_SNIPPET": candidate.evidence_snippet,
        }),
    )

    # Call 2: meaning translation
    meaning = translator.generate_text(
        model_name=translator_model_name,
        prompt=render_named_sections(meaning_prompt, {
            "MEANING_ZH": candidate.meaning_zh,
        }),
    )

    save_idiom_translation(
        conn,
        candidate_id=candidate.candidate_id,
        translation_run_id=run_id,
        target_term=rendering,
        meaning_en=meaning,
        translator_model_name=translator_model_name,
        translator_prompt_version=rendering_prompt_version,
    )
```

### `save_idiom_translation()` — updated

```sql
UPDATE idiom_candidates
SET preferred_rendering_en = ?,
    meaning_en = ?,
    translation_run_id = ?,
    translator_model_name = ?,
    translator_prompt_version = ?,
    candidate_status = 'translated',
    updated_at = CURRENT_TIMESTAMP
WHERE candidate_id = ?
```

## Pipeline Changes

### `preprocess_idioms()` entry point

```python
rendering_prompt = load_prompt("idiom_translate.txt")
meaning_prompt = load_prompt("idiom_meaning.txt")
```

Both loaded upfront, passed to `translate_idiom_candidates()`.

### `translate_idiom_candidates()` signature

```python
def translate_idiom_candidates(
    *,
    conn: sqlite3.Connection,
    release_id: str,
    run_id: str,
    translator_client: LLMClient,
    translator_model_name: str,
    rendering_prompt_template: str,
    rendering_prompt_version: str,
    meaning_prompt_template: str,
    meaning_prompt_version: str,
    stop_token: StopToken | None = None,
) -> int:
```

### Promotion (`promote_policies`)

The promotion SQL in `idiom_repo.py` copies `meaning_en` from `idiom_candidates` to `idiom_policies`:

```sql
INSERT INTO idiom_policies(
    idiom_id, release_id, source_text, normalized_source_text,
    meaning_zh, meaning_en, preferred_rendering_en, ...
) ...
```

## Validation Changes

### `merge_idiom_candidates()`

```python
if not merged_meaning and candidate.meaning_zh.strip():
    merged_meaning = candidate.meaning_zh.strip()
if not merged_meaning_en and candidate.meaning_en.strip():     # NEW
    merged_meaning_en = candidate.meaning_en.strip()            # NEW
if not merged_rendering and candidate.preferred_rendering_en.strip():
    merged_rendering = candidate.preferred_rendering_en.strip()
```

### `make_promotion_entry()`

```python
meaning_zh=existing.meaning_zh if existing is not None else merged_meaning,
meaning_en=existing.meaning_en if existing is not None else merged_meaning_en,  # NEW
```

## Hash Consideration

`_hash_idiom_policies()` in `packets/builder.py` does **not** include `meaning_en`. Rationale: `meaning_en` is not consumed by any downstream stage that uses packet hashes (packet rebuilding, staleness detection). Including it would cause unnecessary cache invalidation. When a future task consumes `meaning_en` in packet content, the hash should be updated then.

## Backward Compatibility

| Scenario | Behaviour |
|---|---|
| Existing DB rows with `meaning_en` column | Created afresh (pre-alpha, dev DBs get deleted) |
| Old idiom candidates without `meaning_en` | `save_idiom_translation()` will set it; old untranslated rows have `""` default |
| `IdiomCandidate`/`IdiomPolicy` constructed without `meaning_en` | Default `""` — no crash, existing tests pass |

## Out Of Scope

- Adding `meaning_en` to packet bundles, `build_paragraph_bundle()`, or `_format_idiom_entry()`.
- Including `meaning_en` in `_hash_idiom_policies()`.
- TUI or CLI display of `meaning_en`.
- Any schema migration beyond the new column — handled by `ensure_full_schema()`.
