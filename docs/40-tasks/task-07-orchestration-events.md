# Task 07: Orchestration And Events (M10)

- **Milestone:** M10
- **Depends on:** M1–M9 (all prior milestones must have stable callable entrypoints)

## Goal

Implement centralized run control, retries, resume behavior, cleanup planning, and structured events.

## Scope

In:

- orchestration runner
- event models and emission
- cleanup plan/apply workflow

Out:

- TUI widget details

## Owned Files Or Modules

- `src/resemantica/orchestration/`
- `src/resemantica/tracking/`
- `tests/orchestration/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-07-orchestration-events.md`

## Tests Or Smoke Checks

- legal/illegal stage transitions
- retry event emission
- cleanup plan/apply contract

## Done Criteria

- orchestration is the single execution authority
- resume uses persisted checkpoints
- cleanup is hash- and scope-aware
