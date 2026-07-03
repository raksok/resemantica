# LLD 74: Pass2 Block Retry Recovery

## Summary

Pass 2 now retries transient validation failures at the block task boundary before failing the chapter. This keeps batched translation moving when one analyst response drops placeholders or otherwise fails structure once, without rerunning successful blocks in the same chapter pass.

## Design

`TranslationConfig` adds `pass2_validation_retries`, read from `[translation]` TOML. The value is the number of additional validation attempts after the first pass2 block attempt, defaults to `2`, and must be `>= 0`.

`translation.pipeline._process_pass2_block()` wraps the existing pass2 block logic:

- structural validation failures are retryable;
- blocking placeholder restoration failures are retryable;
- fidelity validation failures retry while attempts remain, then keep the existing failed-artifact path;
- prompt budget and other non-validation exceptions are not retried here.

For resegmented pass1 blocks, the whole pass2 block task retries as a unit. Segment order and prior-segment context are rebuilt from the start of that attempt.

Each retry emits `pass2.retry` with chapter number, block or segment id, attempt, max attempts, remaining retries, and reason. Exhausted failures keep the existing `pass2.failed` and chapter/stage failure behavior.

## Retry-Failed Planning

`run retry-failed --stage translate-range` treats translation checkpoint `status = 'success'` as complete. Missing, failed, or incomplete pass3 state remains retryable through normal `translate-range` resume behavior.

## Tests

- pass2 structural failure succeeds after one block retry
- pass2 retry exhaustion fails the chapter
- successful sibling blocks are not retried by the block retry wrapper
- `pass2_validation_retries = 0` preserves immediate failure
- resegmented block retry preserves ordered segment processing
- translation retry planning recognizes successful pass checkpoints
