# Task 43: Pipeline Reliability Gates Kaizen

## Milestone
M43

## Depends On
M42, M20C, M16

## Goal
Prevent unsafe production and resume runs from flowing into expensive LLM stages or final EPUB reconstruction when required upstream artifacts are missing, stale, or unresolved.

## Scope
- Keep extraction as a separate setup step (`rsem extract`).
- Add deterministic orchestration gates before each production stage.
- Fail production and resume runs early with actionable missing-artifact details.
- Include gate preview metadata in `run production --dry-run`.
- Preserve standalone commands; they remain usable as direct operator tools.

## Owned Files Or Modules
- `src/resemantica/orchestration/gates.py`
- `src/resemantica/orchestration/runner.py`
- `src/resemantica/orchestration/resume.py`
- `src/resemantica/epub/rebuild.py`
- `tests/orchestration/`
- `docs/20-lld/lld-43-pipeline-reliability-gates.md`

## Interfaces To Satisfy
- `STAGE_ORDER` starts with `preprocess-summaries` (summaries before glossary).
- `run production --dry-run` returns the ordered plan with per-stage gate metadata.
- `run production` and `run resume` enforce the same gates before launching production stages.
- Gate failures return `StageResult(success=False, ...)` and persist a `*.gate_failed` event.
- No bypass flag is added.

## Tests Or Smoke Checks
- Gate tests cover missing extraction manifest/chapter files.
- Gate tests cover unresolved glossary and idiom rendering votes.
- Gate tests cover non-story chapters being allowed to skip downstream packet, translation, and rebuild requirements.
- Gate tests cover missing packet and rebuild artifacts.
- Runner tests cover production failure before stage execution and dry-run gate preview metadata.
- Glossary discovery skips chapters marked `is_story_chapter = 0` in `summary_drafts`.
- Run focused orchestration tests, then Ruff and mypy for changed modules.

## Done Criteria
- Production/resume fail fast before unsafe stages.
- Gate messages identify missing inputs.
- Dry-run exposes gate preview metadata.
- Focused tests, Ruff, and mypy pass.
