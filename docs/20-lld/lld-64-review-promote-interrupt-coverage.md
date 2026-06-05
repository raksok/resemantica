# LLD 64: Review/Promote Interrupt Coverage

## Summary

Glossary and idiom review/promote commands participate in the standard two-stage Ctrl+C flow. The direct review commands now install the shared CLI interrupt handlers by passing a `StopToken` to `_with_cli_progress()`, and review pipelines poll that token at file-generation checkpoints.

Promotion commands already accepted `StopToken`; they now poll it at additional review-file, validation, promotion, and snapshot boundaries.

## Command Flow

`glossary-review` and `idiom-review`:

1. CLI creates the preprocess-level `StopToken`.
2. CLI passes the token to `_with_cli_progress()`.
3. CLI passes the same token into the review pipeline.
4. Review pipelines call `raise_if_stop_requested()` before work starts, after DB load, before JSON write, after JSON write, and after CSV write.

`glossary-promote` and `idiom-promote`:

1. CLI continues passing the token to `_with_cli_progress()` and the promote pipeline.
2. Promote pipelines check for stops after review-file reads, after review overrides, around validation, before and after durable promotion writes, and around snapshot artifacts.

## Failure Boundary

`StopRequested` is not an operational failure. Review/promote `.failed` events remain reserved for unexpected exceptions. Graceful stops return through the existing interrupted/stopped path and should not emit `.failed`.

## Out Of Scope

- Graph interrupt hardening.
- New CLI flags.
- Review file schema changes.
- Database schema or promotion validation changes.
- Event name changes.

## Validation

- CLI tests verify token wiring for review commands.
- Glossary and idiom pipeline tests verify graceful stops do not emit failed events.
- Existing review/promote behavior tests continue to cover generated files, edits, additions, conflicts, and artifacts.
