# Task 64: Review/Promote Interrupt Coverage

## Milestone

M64

## Depends On

M63

## Goal

Make glossary and idiom review/promote commands honor the documented two-stage Ctrl+C behavior.

## Scope

- Install the CLI interrupt handler for direct `glossary-review` and `idiom-review` commands.
- Pass `StopToken` into glossary and idiom review pipelines.
- Add cooperative stop checkpoints around review DB reads, review artifact writes, review-file promotion, validation, promotion writes, and snapshot writes.
- Keep graceful `StopRequested` separate from unexpected failure events.
- Leave graph interrupt hardening for a later task.

## Owned Files Or Modules

- `src/resemantica/cli.py`
- `src/resemantica/glossary/pipeline.py`
- `src/resemantica/idioms/pipeline.py`
- Existing CLI, glossary, and idiom tests
- Task, LLD, command, and interrupt documentation

## Interfaces

Review functions accept an optional `stop_token` parameter. This is additive and backward-compatible.

No CLI flags, review file formats, database schemas, event names, or promotion semantics change.

## Tests

- CLI dispatch tests assert review commands pass the same token to `_with_cli_progress()` and the review pipeline.
- Glossary and idiom tests assert requested stops raise `StopRequested`.
- Graceful stops do not emit `.failed` review/promote events.

## Done Criteria

- First Ctrl+C on review/promote commands requests graceful stop and returns through the existing interrupted path.
- Second Ctrl+C remains force-exit behavior from the shared CLI handler.
- Targeted tests and Ruff pass.
