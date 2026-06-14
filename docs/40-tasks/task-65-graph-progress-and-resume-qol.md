# Task 65: Graph Progress And Resume QoL

## Milestone

M65

## Depends On

M64

## Goal

Improve graph pipeline operator feedback and retry precision without changing graph extraction semantics.

## Scope

- Add graph extraction progress and resume summary events.
- Emit graph snapshot and warnings artifact events.
- Make CLI progress display graph resume/progress/artifact details clearly.
- Make `retry-failed` graph planning detect missing or stale extraction drafts using source hash and prompt version.
- Update graph command, storage, architecture, and troubleshooting docs.

## Owned Files Or Modules

- `src/resemantica/graph/pipeline.py`
- `src/resemantica/cli_progress.py`
- `src/resemantica/orchestration/retry_failed.py`
- Graph, CLI progress, and retry-failed tests
- Manual, task, and LLD documentation

## Interfaces

No new CLI flags or graph schemas are added. `preprocess_graph()` return metadata gains additive draft/progress counters.

## Tests

- Graph pipeline tests assert progress, resume summary, forced rebuild, and artifact events.
- CLI progress tests assert graph console log formatting and artifact counting.
- Retry-failed tests assert missing, stale, and fresh-failed graph draft behavior.

## Done Criteria

- `preprocess graph` visibly reports chapter progress and draft reuse.
- Retry planning identifies stale graph drafts before execution.
- Targeted tests and Ruff pass.
