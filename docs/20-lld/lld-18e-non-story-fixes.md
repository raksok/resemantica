# LLD 18e: Non-Story Detection Bug Fixes & Manual Override CLI

## Summary
Three fixes for the non-story chapter detection system:
1. Fix dead control flow in `generate_chapter_summary` that prevented non-story chapters from receiving the correct `validation_status`.
2. Add a source-text length guardrail to catch LLM hallucination of `is_story_chapter: false` for real narrative chapters.
3. Add a `set-chapter-flag` CLI command for manual override when the guardrail misses an edge case.

## Problem Statement

### Bug 1: Dead Code / Wrong Validation Status
LLD 18b specifies that non-story drafts should have `validation_status='non_story_chapter'`. However, the implementation in `generate_chapter_summary` has dead code (lines 312-320) that is never reached:

1. LLM returns `is_story_chapter: false`.
2. `validate_chinese_summary()` detects this and adds error code `non_story_chapter_flagged`.
3. The `if not validation.is_valid` branch fires, saving the draft as `validation_status="failed"` and returning `None`.
4. The `if is_story == 0` block at line 312 is **never reached**.

The draft ends up with `validation_status="failed"` instead of the intended `"non_story_chapter"`.

### Bug 2: No Guardrail Against LLM Hallucination
When the LLM incorrectly sets `is_story_chapter: false` for a real story chapter, there is no recovery path. The chapter is permanently skipped from summaries, idioms, graph, and packet building with no visibility to the operator.

## Technical Design

### Fix 1: Control Flow Restructure

Move the non-story check (`is_story == 0`) **before** the validation call in `generate_chapter_summary`. When the LLM returns `is_story_chapter: false` (and the guardrail does not override — see Fix 2):

1. Save the draft with `is_story_chapter=0` and `validation_status='non_story_chapter'`.
2. Return `None` immediately — skip validation entirely.

This avoids irrelevant schema validation failures on empty fields (setting, tone) that are expected per the non-story prompt instructions.

`generator.py` flow after the fix:
```
parse → is_story_chapter
  ↓
if is_story_chapter is False:
  → guardrail check (Fix 2)
  → if overridden: is_story_chapter = True, continue as story
  → if NOT overridden:
      save draft (is_story=0, status="non_story_chapter")
      return None
  ↓
save draft (is_story=1, status="pending")
validate → fail? → save "failed" → return None
save validated summary → return it
```

### Fix 2: Source-Text Length Guardrail

Add a guardrail helper in `generate_chapter_summary` that checks the actual chapter source text length before accepting the LLM's non-story classification:

```python
_NON_STORY_GUARDRAIL_LENGTH = 500

if is_story_chapter is False and len(source_text_zh) > _NON_STORY_GUARDRAIL_LENGTH:
    logger.warning("Overriding non-story flag for chapter {} ...", chapter_number)
    is_story_chapter = True
```

**Threshold rationale (500 Chinese characters):**
| Content | Typical Length |
|---------|---------------|
| Copyright page | ~30 chars |
| Dedication | ~10-50 chars |
| Table of Contents | ~50-200 chars |
| Author's note / preface | ~50-500 chars |
| Story chapter | 1000+ chars |

500 chars is above most front-matter but below typical narrative chapters. Long front-matter (prefaces, forewords) that exceed this threshold are rare and can be corrected with the CLI command (Fix 3).

**When the guardrail triggers:**
- `is_story_chapter` is set to `True`.
- Draft saved with `is_story=1`, `validation_status="pending"`.
- Validation runs against the (empty) story fields and fails — saved as `"failed"`.
- `generate_chapter_summary` returns `None`.
- `is_non_story_chapter()` returns `False` (column value is 1).
- Downstream pipelines: graph/idioms extract from source text successfully; packet builder skips with `missing_story_so_far_summary`.
- Pipeline reports the chapter as `generation_failed` (visible to the operator).
- Operator can investigate and re-run with adjusted settings if needed.

### Fix 3: CLI Command `set-chapter-flag`

**New repo function** in `db/summary_repo.py`:

```python
def set_chapter_story_flag(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    chapter_number: int,
    is_story: bool,
) -> bool:
```

Updates the `summary_drafts` table:
- `is_story_chapter` = 1 (story) or 0 (non-story)
- `validation_status` = `"pending"` (story) or `"non_story_chapter"` (non-story)
- `updated_at` = current timestamp

Returns `True` if a row was updated, `False` if no draft exists.

**CLI registration** as a top-level command:

```
rsem set-chapter-flag -r <release> -C <chapter> {--story | --non-story}
```

Alias: `scf`

Two use cases:
- `--story`: Fix a story chapter that the LLM (or guardrail) misclassified as non-story. Sets `is_story_chapter=1`, `validation_status="pending"`. Re-running the summaries pipeline will attempt regeneration.
- `--non-story`: Fix a non-story chapter (e.g., author's commentary, afterword) that was misclassified as story. Sets `is_story_chapter=0`, `validation_status="non_story_chapter"`. Downstream pipelines will skip it.

## Data Flow (Corrected)

Updated flow for non-story chapters after Fix 1:

1. `preprocess_summaries` calls `generate_chapter_summary`.
2. Analyst LLM receives source text and prompt.
3. Guardrail checks `len(source_text_zh) > 500` (Fix 2).
4. If guardrail overrides → continue as story (validation fails → `generation_failed`).
5. If truly non-story → save draft with `is_story_chapter=0`, `validation_status='non_story_chapter'`, return `None`.
6. `preprocess_summaries` records the chapter as `{"status": "skipped", "reason": "non_story_chapter"}`.
7. Downstream pipelines query `is_non_story_chapter()` and skip the chapter.

## Prompt Update
Add "Author's commentary, afterword, or end-of-book notes" to the non-story content categories in `summary_zh_structured.txt`. This reduces the likelihood of LLM misclassification for these legitimate non-story sections.

## Files Changed
| File | Change |
|------|--------|
| `src/resemantica/summaries/generator.py` | Fix 1 + Fix 2 — restructure control flow, add guardrail |
| `src/resemantica/db/summary_repo.py` | Fix 3 — add `set_chapter_story_flag()` |
| `src/resemantica/cli.py` | Fix 3 — add `set-chapter-flag` parser + dispatch |
| `src/resemantica/llm/prompts/summary_zh_structured.txt` | Add author's commentary to non-story categories |
| `docs/20-lld/lld-18b-non-story-chapter-detection.md` | Note the control flow bug fix |
| `tests/summaries/test_summary_pipeline.py` | Update existing test & add guardrail test |
| `tests/db/test_summary_repo.py` | Add `set_chapter_story_flag` test |

## Appendix: Graph Extract Prompt Overhaul (v1.0 → v2.0)

Three issues observed in production graph extraction runs:

### Issue 1: Mixed-Language Entity Names
The LLM was outputting English/transliterated names (`Chen Ping'an`, `Niping Alley`, `Move mountains`) instead of the original Chinese from the source text (`陈平安`, `尼平巷`, `搬山`). The prompt only had a single line ("exact Chinese text as it appears") buried in the Entities section.

**Fix:** Added a prominent language block at the top of OUTPUT FORMAT:
```
ALL text fields must be in the original Chinese from the source text.
NEVER translate or transliterate names into English.
```
And reinforced `source_term`/`target_term` with "(NEVER translate — Chinese only)".

### Issue 2: No Relationships Extracted Despite Clear Links
A chapter with text like "我陈平安，唯有一剑，可搬山，倒海" extracted 10 entities (Chen Ping'an + 9 techniques) but zero relationships. The USES_TECHNIQUE relationship type existed in the schema but the LLM wasn't using it.

**Fix:** Added explicit emphasis under Relationships:
```
Every extracted entity should participate in at least one relationship.
Missing a relationship is worse than including a speculative one.
```
And a domain-specific note for cultivation novels.

### Issue 3: No Guardrail Against Natural Language Responses
If the LLM responds "This chapter has no entities to extract" instead of `{"entities": [], "relationships": []}`, `json.loads` raises `JSONDecodeError`. The caller catches it and skips the chapter with `reason="parse_error"`, but the chapter should be treated as a valid empty result.

**Fix (prompt):** Added:
```
If no entities or relationships are found, return {"entities": [], "relationships": []}.
Do NOT wrap JSON in markdown code fences. Return raw JSON only.
```

**Fix (code):** Added a fallback in `_parse_llm_response` (`extractor.py:178`): when `json.loads` fails and the response contains no `{`/`}` characters (i.e., pure natural language), return `([], [])` instead of raising.

### Files Changed (Appendix)
| File | Change |
|------|--------|
| `src/resemantica/llm/prompts/graph_extract.txt` | Version 1.0 → 2.0: language enforcement, relationship emphasis, empty-result guardrail, no-markdown instruction |
| `src/resemantica/graph/extractor.py` | `_parse_llm_response`: natural language fallback returning `([], [])` |

## Out of Scope
- Automatic re-processing after guardrail override.
- User-facing retry logic or "force regenerate" for guardrail-caught chapters.
- Adding columns to `validated_summaries_zh`.
- Changes to downstream pipeline skip logic.
