# Task 14: Batch Pilot

- **Milestone:** M14
- **Depends on:** M10–M13

## Goal

Run a 10-50 chapter pilot through the complete production workflow and produce validated EPUB and quality reports.

## Scope

In:

- representative pilot chapter selection
- full preprocessing and packet generation
- orchestrated translation with checkpoints and observability
- final EPUB rebuild and pilot report

Out:

- full-book production beyond the pilot
- new major architecture features
- manual ad hoc assembly outside orchestration

## Owned Files Or Modules

- pilot fixtures or operator-selected pilot inputs
- generated artifacts under `artifacts/`
- any targeted fixes required by pilot-blocking defects

## Interfaces To Satisfy

- LLD: `../20-lld/lld-14-pilot.md`
- CLI: `uv run python -m resemantica.cli run production`
- CLI: `uv run python -m resemantica.cli rebuild-epub`
- TUI: `uv run python -m resemantica.cli tui`

## Tests Or Smoke Checks

- 10-50 chapter production pilot completes or records actionable failures
- final EPUB structural validation
- warning, retry, and quality metrics inspected through observability outputs
- targeted rerun after any blocking fix uses resume or cleanup scope rather than full restart

## Done Criteria

- pilot translates the selected chapter range through orchestration
- final translated EPUB is rebuilt from translated outputs
- pilot report summarizes quality, failures, cleanup behavior, and readiness for broader runs
- enough artifacts remain to debug failures without rerunning the full pilot
