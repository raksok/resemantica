# LLD 81: Graceful Task-Level Drain And Exit

## Summary

Graceful stop is coordinated by `StopToken` at durable task boundaries. Concurrent LLM phases use a shared bounded scheduler rather than submitting an entire phase eagerly. On the first stop request, the scheduler admits no more work, cancels futures that have not started, drains active futures through the normal persistence callback, and returns a `DrainResult`.

## Concurrency And Persistence

`run_interruptible_pool()` maintains at most `max_workers` futures. Translation Pass 2 and the summary/continuity pools cap this value with `LLMClient.concurrency_limit()` so executor workers do not wait invisibly behind the per-model semaphore.

Pass 1 writes a reusable partial artifact after each block. Pass 2 writes a reusable partial artifact after each completed work unit. Both use `status="stopped"` before propagating `StopRequested`. Summary and continuity workers retain their existing database writes; the consumer advances only the contiguous checkpoint prefix and writes completed artifacts before stop propagation.

Sequential glossary, idiom, graph, packet, and translation loops continue polling between durable units. Running HTTP generations are not canceled.

## Reporting

`InterruptReport` contains the stage, phase, unit kind, completed count, drained count, canceled count, last durable unit, next resumable unit, checkpoint, and LLM usage. `run_stage()` stores it in the stopped event and run-state metadata. The CLI renders it in the Stage Result before returning 130. TUI workers show the drained/canceled summary and return the app to idle.

`retry-failed` forwards the shared token and emits `retry-failed.stopped`. It retains the existing restoration of the production run state while preserving the interrupt report in retry telemetry and the returned result.

## Failure Boundary

`StopRequested` is control flow, not failure. Concurrent and chunk-level exception handlers must re-raise it before generic exception handling. Second Ctrl+C remains `os._exit(130)` and may leave partial work.
