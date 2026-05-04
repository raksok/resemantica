# Task 18e: Non-Story Detection Bug Fixes & Manual Override CLI

## Goal
Fix two bugs in the non-story chapter detection system — dead control flow in `generate_chapter_summary` and missing guardrail against LLM hallucination — and add a `set-chapter-flag` CLI command for manual override.

## Scope

In:
- Restructure `generate_chapter_summary` so the non-story check runs before validation (fixing dead code at lines 312-320 and giving drafts proper `validation_status="non_story_chapter"`).
- Add a source-text length guardrail (>500 chars) that overrides the LLM's `is_story_chapter: false` classification when the chapter clearly contains narrative content.
- Add `set_chapter_story_flag()` repo function in `summary_repo.py`.
- Add `rsem set-chapter-flag` (alias `scf`) top-level CLI command with `--story` / `--non-story` flags.
- Add author's commentary/afterword to the prompt's non-story category list.
- Update the integration test for non-story pipeline to verify DB status; add guardrail override test; add repo function test.

Out:
- Modifying downstream pipeline skip logic (`idioms/pipeline.py`, `graph/pipeline.py`, `packets/builder.py`) — they already call `is_non_story_chapter()` correctly.
- Automatic recovery after guardrail override (user re-runs relevant stage manually).
- Changes to the DB schema (no migration needed; column already exists).

## Owned Files Or Modules
- `src/resemantica/summaries/generator.py`
- `src/resemantica/db/summary_repo.py`
- `src/resemantica/cli.py`
- `src/resemantica/llm/prompts/summary_zh_structured.txt`
- `docs/20-lld/lld-18b-non-story-chapter-detection.md`
- `tests/summaries/test_summary_pipeline.py`
- `tests/db/test_summary_repo.py`

## Interfaces To Satisfy
- `summary_repo.set_chapter_story_flag(conn, *, release_id, chapter_number, is_story: bool) -> bool`
- CLI: `rsem set-chapter-flag -r <release> -C <chapter> {--story | --non-story}`

## Tests Or Smoke Checks
- **Update:** `test_non_story_chapter_pipeline_skipped` — add DB assertion verifying `validation_status="non_story_chapter"`.
- **New:** `test_guardrail_overrides_non_story` — chapter with >500 chars source text flagged as non-story by LLM; verify pipeline reports `generation_failed` (not `non_story_chapter`).
- **New:** `test_set_chapter_story_flag` — toggle flag both directions; verify DB state and missing-chapter return value.

## Done Criteria
- `generate_chapter_summary` saves non-story drafts with `validation_status="non_story_chapter"` (not "failed").
- Chapters with `len(source_text_zh) > 500` incorrectly flagged as non-story are overridden to story, reported as `generation_failed`.
- `rsem set-chapter-flag -r <id> -C <n> --story/--non-story` updates the database and prints confirmation.
- Prompt lists "Author's commentary, afterword, or end-of-book notes" as a non-story category.
- All existing and new tests pass.
- LLD 18e documents the fixes; LLD 18b updated to note the control flow bug fix.
