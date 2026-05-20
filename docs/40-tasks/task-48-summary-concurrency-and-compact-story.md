# Task 48: Summary Concurrency And Compact Story

## Milestone

M48

## Depends On

M45, M46, M47

## Goal

Split `preprocess-summaries` into concurrent chapter-local Chinese work, ordered Chinese story assembly, and concurrent English derivation while adding bounded compact Chinese continuity.

## Scope

- Add `[summaries]` settings for `chapter_concurrency` and `story_compact_max_tokens`.
- Add `story_so_far_zh_compact` as a validated Chinese summary type.
- Keep `story_so_far_zh` as full cumulative continuity.
- Derive English `story_so_far_en` from compact Chinese continuity.
- Make packets prefer compact continuity and fall back to full continuity for older releases.
- Extend summary checkpoints with `story_last_chapter`.

## Owned Files Or Modules

- `src/resemantica/settings.py`
- `src/resemantica/db/sqlite.py`
- `src/resemantica/db/summary_repo.py`
- `src/resemantica/summaries/`
- `src/resemantica/llm/prompts/summary_story_compact.txt`
- `src/resemantica/packets/builder.py`
- `tests/summaries/`
- `tests/packets/`
- `tests/test_settings_models.py`
- `docs/20-lld/lld-04-summaries.md`
- `docs/20-lld/lld-08-packets.md`
- `docs/20-lld/lld-45-local-model-batched-inference-kaizen.md`

## Interfaces To Satisfy

- External CLI and orchestration stage names remain unchanged.
- Summary artifacts remain `chapter-*-zh.json` and `chapter-*-en.json`.
- `chapter-*-zh.json` includes `story_so_far_zh_compact` for story chapters.
- Packet `story_so_far_summary` prefers `story_so_far_zh_compact`.
- `summary_checkpoints` exposes `zh_last_chapter`, `story_last_chapter`, and `en_last_chapter`.

## Tests Or Smoke Checks

- Config defaults and invalid values.
- Out-of-order Chinese generation with ordered full and compact story rows.
- Compact story generation from previous compact plus current short summary.
- Compact story over-budget drafts are repaired once and only under-budget compact results are cached.
- English story derivation from compact Chinese continuity.
- Empty compaction output, or output still over budget after repair, fails `preprocess-summaries`.
- Packet compact preference, full fallback, and summary hash invalidation.

## Done Criteria

- Focused summaries, packets, and settings tests pass.
- Full test suite passes.
- Ruff, mypy, and `git diff --check` pass.
- LLDs document the three internal phases and compact continuity ownership.
