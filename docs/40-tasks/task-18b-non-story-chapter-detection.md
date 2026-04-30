# Task 18b: Non-Story Chapter Detection

## Goal
Implement LLM-based detection and skipping of non-story chapters to prevent junk summaries and world-model pollution.

## Scope
In:
- Update `summary_zh_structured.txt` prompt template.
- Update `summaries.validators.validate_chinese_summary` to support the `is_story_chapter` flag.
- Update `summaries.generator.generate_chapter_summary` to persist the non-story status.
- Update `summaries/pipeline.py` to report skipped chapters with a reason.
- Update `idioms/pipeline.py`, `graph/pipeline.py`, and `packets/builder.py` to skip chapters flagged as non-story in the database.
- Create DB migration `009_is_story_chapter.sql` adding `is_story_chapter` column to `summary_drafts`.
- Add `is_non_story_chapter(conn, release_id, chapter_number) -> bool` query to `summary_repo.py`.

Out:
- Modifying extraction logic inside `extractor.py` (pipelines handle the skip via DB query).
- Adding columns to `validated_summaries_zh` (non-story chapters never produce rows there).

## Owned Files Or Modules
- `src/resemantica/llm/prompts/summary_zh_structured.txt`
- `src/resemantica/summaries/validators.py`
- `src/resemantica/summaries/generator.py`
- `src/resemantica/summaries/pipeline.py`
- `src/resemantica/idioms/pipeline.py`
- `src/resemantica/graph/pipeline.py`
- `src/resemantica/packets/builder.py`
- `src/resemantica/db/summary_repo.py`
- `src/resemantica/db/migrations/009_is_story_chapter.sql`

## Interfaces To Satisfy
- `chapter_summary_zh_structured` JSON schema (adds `is_story_chapter: boolean`).
- `SummaryValidationResult` gains error code `non_story_chapter_flagged`.
- `summary_repo.is_non_story_chapter(conn, release_id, chapter_number) -> bool`.

## Database Migration
New migration `009_is_story_chapter.sql`:

```sql
ALTER TABLE summary_drafts ADD COLUMN is_story_chapter INTEGER NOT NULL DEFAULT 1;
```

The column uses SQLite boolean convention (1 = story, 0 = non-story). Default is 1 so existing rows are unaffected. When a non-story chapter is detected, the draft is saved with `is_story_chapter=0` and `validation_status='non_story_chapter'`.

## Downstream Query Pattern
Idioms, graph, and packets pipelines call:

```python
from resemantica.db.summary_repo import is_non_story_chapter

if is_non_story_chapter(conn, release_id, chapter_number):
    # skip this chapter
```

## Tests Or Smoke Checks
- **Unit Test:** Provide a mock front-matter text (e.g., Copyright page) to `validate_chinese_summary` with `is_story_chapter: false` and verify it fails with error code `non_story_chapter_flagged`.
- **Integration Test:** Run a mock preprocessing pass on a mix of story and non-story chapters and verify the non-story ones produce `{"status": "skipped", "reason": "non_story_chapter"}` in the final results.

## Done Criteria
- `is_story_chapter` is a mandatory field in the summary analyst prompt.
- Chapters flagged as `is_story_chapter: false` do not produce entries in `validated_summaries_zh`.
- The `preprocess summaries` command reports these chapters as `{"status": "skipped", "reason": "non_story_chapter"}`.
- Migration `009_is_story_chapter.sql` adds the column with default `1`.
- `is_non_story_chapter()` query function exists in `summary_repo`.
- Idioms, graph, and packets pipelines skip non-story chapters using the query.
- Unit tests cover the validation logic for the new flag.
