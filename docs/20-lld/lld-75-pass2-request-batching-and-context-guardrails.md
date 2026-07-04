# LLD 75: Pass2 Request Batching And Context Guardrails

## Summary

Pass 2 audits normal Pass 1 blocks in token-bounded batches by default. The Qwen throttle-group `system_prompt` remains unchanged and stays in the LLM client request layer; Pass 2 batching only changes user prompt shape and scheduling.

Resegmented blocks continue to use the existing sequential segment path because each segment depends on prior segment translations.

## Configuration

`[translation].pass2_batch_max_blocks` controls the maximum normal blocks per batch.

```toml
[translation]
pass2_batch_max_blocks = 8
```

- Default: `8`
- Validation: must be `>= 1`
- `1` restores the current one-block request scheduling path.

`pass2_concurrency` is unchanged. The executor now schedules Pass 2 work units, where a work unit is either one resegmented block, one compatibility single-block request, or one normal-block batch.

## Prompt Contract

`translate_pass2_batch.txt` keeps stable instructions and the output schema before the dynamic `BATCH_JSON` payload. This preserves KV-cache-friendly prefix layout while keeping per-block context in the user prompt.

The batch output schema is:

```json
{"results":[{"block_id":"...","fidelity_errors_found":false,"corrected_text":""}]}
```

The global Qwen `system_prompt` is not moved into the prompt template.

## Batch Packing

Normal blocks are greedily packed in original order until either:

- `pass2_batch_max_blocks` is reached, or
- the rendered batch user prompt plus the configured matching throttle-group system prompt exceeds the Pass 2 prompt budget.

If one block cannot fit in the batch prompt, it falls back to the existing single-block path. If that single-block prompt is also over budget, the existing prompt-budget guard fails before the LLM call.

## Fallback

Batch recovery reruns only affected blocks through `_process_pass2_block()` and its existing `pass2_validation_retries` loop.

Fallback reasons include:

- invalid batch JSON
- missing, duplicate, or unexpected block IDs
- invalid result object shape
- empty `corrected_text` when `fidelity_errors_found` is true
- structural, restoration, or fidelity validation failure for an individual batch result

Valid unaffected batch results are preserved.

## Artifacts And Events

`pass2.json` keeps the existing `blocks` shape. New optional metadata records:

- `batch_prompt_version`
- `batching.enabled`
- `batching.max_blocks`
- `batching.batches_attempted`
- `batching.batch_fallbacks`
- `batching.batch_fallback_blocks`

Events:

- `translate-chapter.pass2.batch_started`
- `translate-chapter.pass2.batch_completed`
- `translate-chapter.pass2.batch_fallback`

Payloads include `batch_index`, `block_count`, `block_ids`, `prompt_token_count`, elapsed seconds where applicable, and fallback reason for fallback events.

## Validation

Tests cover default batching, max-block splitting, system prompt budget overhead, invalid batch fallback, targeted per-block fallback, resegmented block isolation, and `pass2_batch_max_blocks = 1`.
