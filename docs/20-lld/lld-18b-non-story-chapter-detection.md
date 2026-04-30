# LLD 18b: Non-Story Chapter Detection

## Summary
Implement a mechanism for the LLM Analyst to explicitly identify and flag non-story chapters (front-matter, author notes, copyright pages, etc.) during the preprocessing stage. This acts as a robust content-based guardrail alongside existing regex-based filename filtering.

## Problem Statement
Regex-based filename filtering (e.g., `toc.xhtml`, `copyright.xhtml`) is effective but fragile. Publishers often mislabel front-matter as numbered chapters (e.g., `chapter-001.json` containing only a dedication). Attempting to summarize these as narrative chapters produces "junk" summaries and pollutes the world model with non-narrative "events".

## Technical Design

### 1. Schema Update
The `chapter_summary_zh_structured` JSON schema will be extended with a mandatory boolean field: `is_story_chapter`.

```json
{
  "chapter_number": 5,
  "is_story_chapter": false,
  "characters_mentioned": [],
  "key_events": [],
  "new_terms": [],
  "relationships_changed": [],
  "setting": "",
  "tone": "",
  "narrative_progression": "Non-story chapter: Table of Contents and Author Introduction."
}
```

### 2. Prompt Modification
The `summary_zh_structured.txt` prompt template will be updated to:
- Define the `is_story_chapter` field.
- Provide clear instructions on what constitutes a "non-story" chapter.
- Instruct the model to set `is_story_chapter: false` and provide a brief explanation in `narrative_progression` when such content is detected.

### 3. Validation Logic
The `summaries.validators.validate_chinese_summary` function will be updated:
- Verify the presence and type of `is_story_chapter`.
- If `is_story_chapter` is `false`, the validation will fail with error code `non_story_chapter_flagged`.
- The `"is_story_chapter"` string is added to the `_REQUIRED_FIELDS` set.

### 4. Database Persistence
A new migration `009_is_story_chapter.sql` adds a boolean column to `summary_drafts`:

```sql
ALTER TABLE summary_drafts ADD COLUMN is_story_chapter INTEGER NOT NULL DEFAULT 1;
```

SQLite boolean convention: `1` = story chapter, `0` = non-story chapter. Default `1` preserves existing rows.

When a non-story chapter is detected:
- The draft is saved with `is_story_chapter=0` and `validation_status='non_story_chapter'`.
- **No row is written to `validated_summaries_zh`** (per the design goal of preventing junk summaries).

A new query function in `summary_repo.py`:

```python
def is_non_story_chapter(conn, release_id, chapter_number) -> bool:
```

Returns `True` if the chapter's latest draft has `is_story_chapter=0`.

### 5. Cross-Pipeline Coordination
The Idioms, Graph, and Packet Builder pipelines will be modified to call `is_non_story_chapter()` before processing a chapter:
- **Idioms (`idioms/pipeline.py`):** Check if the chapter has been flagged as non-story. If so, skip `extract_idioms` for that chapter.
- **Graph (`graph/pipeline.py`):** Check if the chapter has been flagged as non-story. If so, skip `extract_entities` for that chapter.
- **Packet Builder (`packets/builder.py`):** Check if the chapter has been flagged as non-story. If so, return a clean `PacketBuildOutput` with `status="skipped"` and `stale_reasons=["non_story_chapter"]`.

### 6. Summary Pipeline Reporting
`summaries/pipeline.py` will report non-story chapters with a distinct reason:

```python
{"status": "skipped", "reason": "non_story_chapter"}
```

This distinguishes them from generation failures which use `{"status": "skipped"}` without a reason field.

This creates a "Summary-First" dependency where running summary preprocessing provides a validated filter for all subsequent stages, preventing translation passes from being attempted on non-narrative content.

## Data Flow
1. `preprocess_summaries` calls `generate_chapter_summary`.
2. Analyst LLM receives source text and prompt.
3. Analyst detects front-matter and returns `is_story_chapter: false`.
4. `validate_chinese_summary` identifies the flag and returns error code `non_story_chapter_flagged`.
5. `generate_chapter_summary` saves the draft with `is_story_chapter=0`, logs the skip, and returns `None`.
6. `preprocess_summaries` records the chapter as `{"status": "skipped", "reason": "non_story_chapter"}`.
7. `preprocess_idioms` / `preprocess_graph` / `packets-build` query `is_non_story_chapter()`, see the flag, and skip the chapter gracefully.

## Out of Scope
- Automatic regex generation for filenames based on LLM findings.
- Retrospective cleanup of previously processed junk summaries (manual reset required).
- Adding `is_story_chapter` to `validated_summaries_zh` (non-story chapters never produce rows there).
