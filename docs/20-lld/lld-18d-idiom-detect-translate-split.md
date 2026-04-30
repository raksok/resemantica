# LLD 18d: Split Idiom Detection and Translation

## Summary
Split the idiom pipeline into two LLM phases — detection (Analyst, Chinese-only) and translation (Translator, produces English rendering) — matching the glossary `discover → translate → promote` pattern.

## Problem Statement
The current `idiom_detect.txt` prompt asks the Analyst model to return both the Chinese meaning and the English rendering in a single call. This conflates two concerns: identifying idioms (a comprehension task) and translating them (a generation task). The Glossary pipeline already separates these, using the Translator model (HY-MT1.5-7B) for term translation while the Analyst focuses on discovery.

## Technical Design

### 1. Phase Split

**Before (one call):**
```
Analyst: extract idioms → {source_text, meaning_zh, preferred_rendering_en, usage_notes}
```

**After (two calls):**
```
Phase 1 — Detect: Analyst → {source_text, meaning_zh, usage_notes}
Phase 2 — Translate: Translator → "plain text English rendering"
```

### 2. Prompt Changes

**`idiom_detect.txt`** — remove `preferred_rendering_en` from the output schema spec:
```json
{
  "source_text": "成语",
  "meaning_zh": "中文解释",
  "usage_notes": "optional usage context"
}
```

**`idiom_translate.txt`** (new) — simple translation prompt like `glossary_translate.txt`:
```
# version: 1.0

## IDIOM_TRANSLATE
Translate this Chinese idiom into concise, natural English.
Return only the translated term with no extra commentary.

SOURCE TEXT: {SOURCE_TEXT}
MEANING (ZH): {MEANING_ZH}
EVIDENCE: {EVIDENCE_SNIPPET}
```

### 3. Extractor Changes

`_DetectedIdiom` drops `preferred_rendering_en`:
```python
@dataclass(slots=True)
class _DetectedIdiom:
    source_text: str
    meaning_zh: str
    usage_notes: str | None
```

`IdiomCandidate` constructed with `preferred_rendering_en=""` instead of reading it from detection output.

### 4. Model Changes

`IdiomCandidate` gains tracking fields (matching `GlossaryCandidate` pattern):
```python
translation_run_id: str | None = None
translator_model_name: str | None = None
translator_prompt_version: str | None = None
```

`IdiomPolicy` — unchanged (still has `preferred_rendering_en`, `usage_notes`).

### 5. Pipeline Changes

`preprocess_idioms()` becomes three phases:

```python
def preprocess_idioms(...):
    # Phase 1: Detect (Analyst)
    detected = extract_idioms(...)
    insert_detected_candidates(...)          # status='discovered'

    # Phase 2: Translate (Translator)
    translate_idiom_candidates(conn, ...)    # status='translated'

    # Phase 3: Promote (no LLM)
    pending = list_candidates_for_promotion(...)  # where status='translated'
    validate_idiom_policy(...)
    promote_policies(...)
```

#### translate_idiom_candidates()

```python
def translate_idiom_candidates(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    run_id: str,
    translator_client: LLMClient,
    translator_model_name: str,
    prompt_template: str,
    prompt_version: str,
) -> int:
    pending = list_candidates_for_translation(conn, release_id=release_id)
    for candidate in pending:
        rendered = translator_client.generate_text(
            model_name=translator_model_name,
            prompt=render(SOURCE_TEXT=candidate.source_text, MEANING_ZH=candidate.meaning_zh, EVIDENCE=candidate.evidence_snippet),
        )
        save_idiom_translation(
            conn,
            candidate_id=candidate.candidate_id,
            translation_run_id=run_id,
            target_term=rendered.strip(),
            translator_model_name=translator_model_name,
            translator_prompt_version=prompt_version,
        )
    return len(pending)
```

### 6. DB Migration

`010_idiom_translate.sql` adds tracking columns to `idiom_candidates`:

```sql
ALTER TABLE idiom_candidates ADD COLUMN translation_run_id TEXT;
ALTER TABLE idiom_candidates ADD COLUMN translator_model_name TEXT;
ALTER TABLE idiom_candidates ADD COLUMN translator_prompt_version TEXT;
```

### 7. Repo Changes

New functions in `idiom_repo.py`:

```python
def list_candidates_for_translation(
    conn, *, release_id: str
) -> list[IdiomCandidate]:
    # SELECT ... WHERE release_id = ?
    #   AND (preferred_rendering_en IS NULL OR preferred_rendering_en = '')
    #   AND candidate_status = 'discovered'

def save_idiom_translation(
    conn, *,
    candidate_id: str,
    translation_run_id: str,
    target_term: str,
    translator_model_name: str,
    translator_prompt_version: str,
) -> None:
    # UPDATE idiom_candidates SET
    #   preferred_rendering_en = ?,
    #   translation_run_id = ?,
    #   translator_model_name = ?,
    #   translator_prompt_version = ?,
    #   candidate_status = 'translated'
    # WHERE candidate_id = ?
```

Existing `list_candidates_for_promotion()` changes its WHERE clause from `candidate_status = 'discovered'` to `candidate_status = 'translated'`.

### 8. Candidate Status State Machine

```
discovered → translated → approved
                     → conflict
```

### 9. CLI and Orchestration

`resemantica preprocess idioms` still calls `preprocess_idioms()` which internally runs all three phases. No CLI changes. In `runner.py`, the `preprocess-idioms` stage dispatching is unchanged — it calls `preprocess_idioms()`.

### 10. Test Changes

`ScriptedIdiomLLM` must route to different mock responses based on prompt type (`IDIOM_DETECT` vs `IDIOM_TRANSLATE`).

New test: mock detection returns idiom without English → verify `preferred_rendering_en=""`.
New test: mock translation returns English rendering → verify field is updated.
Existing promotion/conflict tests unchanged.

## Data Flow

```
Chapter source text
    ↓
[Phase 1] extract_idioms() — Analyst
    ↓  {source_text, meaning_zh, usage_notes}
idiom_candidates: preferred_rendering_en="", status="discovered"
    ↓
[Phase 2] translate_idiom_candidates() — Translator
    ↓  "plain text rendering"
idiom_candidates: preferred_rendering_en="Foo", status="translated"
    ↓
[Phase 3] validate_idiom_policy() + promote_policies()
    ↓
idiom_policies: preferred_rendering_en="Foo", status="approved"
```

## Out of Scope
- Translation explanation field (scrapped by design decision).
- Changes to `IdiomPolicy` or `IdiomConflict` data models.
- CLI command changes.
- Changes to `STAGE_ORDER` or orchestration stage dispatch.
