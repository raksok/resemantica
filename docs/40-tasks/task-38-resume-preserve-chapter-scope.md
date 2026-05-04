# Task 38: Resume Preserves Chapter Scope

## Milestone And Depends On

Milestone: M29

Depends on: M28 (CLI–TUI Feature Parity), M10 (Orchestration + Production)

## Goal

`rsem run resume` should pick up the original chapter range (`--start`/`--end`) from the failed production run so it doesn't overshoot and process all chapters.

## Scope

In:

- Persist `chapter_start`/`chapter_end` into the tracking DB checkpoint when `run_stage` saves its state, so downstream resume can read them
- Extract and forward the chapter range from the checkpoint in `resume_run()`
- Wire `stop_token` through `resume_run()` so the user can Ctrl-C during resume
- Wrap `rsem run resume` in the same `_with_cli_progress()` rich progress bar as `rsem run prod`

Out:

- Backfilling chapter range for existing failed runs (checkpoint is `{}` — user cleans and re-runs)
- Adding `--start`/`--end` flags to the resume command itself (can be added later if needed)
- Any TUI changes

## Owned Files Or Modules

- `src/resemantica/orchestration/runner.py`
- `src/resemantica/orchestration/resume.py`
- `src/resemantica/cli.py`
- `docs/20-lld/lld-38-resume-preserve-chapter-scope.md`

## Interfaces To Satisfy

- `OrchestrationRunner.run_stage()` saves `chapter_start`/`chapter_end` into the checkpoint before persisting to tracking DB
- `resume_run()` accepts `stop_token` parameter and forwards it to `run_stage()` calls
- `resume_run()` reads `chapter_start`/`chapter_end` from `state.checkpoint` and passes them to `run_stage()`
- `rsem run resume` CLI handler wraps execution in `_with_cli_progress(stop_token=...)` matching the production handler

## Tests Or Smoke Checks

- Run `uv run ruff check src/resemantica`
- Run `uv run pytest tests/ -q`
- Manual: `rsem run prod -r <release> -s 1 -e 20` fails → `rsem run resume -r <release>` resumes at correct stage with correct chapter range and rich progress bar

## Done Criteria

- `run_stage()` saves `chapter_start`/`chapter_end` in the tracking DB checkpoint
- `resume_run()` reads and forwards the chapter range to stage execution
- `resume_run()` accepts a `stop_token` parameter
- `rsem run resume` shows the same rich progress bar as `rsem run prod`
- Ch 17–20 appear in resume output; ch 21+ do not
- Ruff passes; existing tests pass
- `docs/20-lld/lld-38-resume-preserve-chapter-scope.md` is implemented and kept in sync
