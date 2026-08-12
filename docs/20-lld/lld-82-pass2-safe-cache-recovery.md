# LLD 82: Pass2 Safe Cache Recovery

## Summary

Pass 2 resume treats validators, not non-empty cached text, as the authority for reuse. This prevents `retry-failed` from promoting an invalid mixed-language output while retaining block-local recovery for large chapters.

## Cache Revalidation

For every compatible cached block, Pass 2 verifies block identity and source text, then rebuilds validation state from the cached candidate:

- normal outputs rerun structural validation;
- resegmented outputs verify ordered segment identities and rerun structure per segment;
- placeholder restoration is rerun and blocking warnings reject reuse;
- restored output reruns deterministic fidelity validation;
- passthrough output must still equal its source exactly.

Only passing blocks enter the reuse map. Their normalized restored text and fresh validation checks seed the rewritten artifact. Missing or failed blocks become new work units. Extra, duplicate, malformed, or identity-mismatched mappings remain hard errors because their intended source cannot be inferred safely.

## Targeted Retry Feedback

The internal single-block Pass 2 call accepts validation feedback. Batch fallback supplies the exact errors that rejected that block, cached-block recovery supplies the errors found during revalidation, and later attempts replace the feedback with errors from the immediately preceding candidate.

Feedback is appended as a runtime `VALIDATION_FEEDBACK` section before prompt-budget validation. It does not change the static fidelity-auditor contract, prompt version, checkpoint key, CLI, or configuration.

## Failure And Events

An exhausted fidelity candidate is retained in `pass2.json` with its failed check. It emits `pass2.failed` with block ID, reason, and exact errors, but does not emit `paragraph_completed`. Structural and restoration exhaustion continue to raise because they cannot produce a safe output mapping. Chapter validation remains failed when any structural or fidelity check fails, and Pass 3 does not start.

## Tests

- invalid mixed-language cached output is repaired while a valid sibling is reused;
- cached validation arrays are rebuilt completely;
- cached and prior-attempt errors reach targeted repair prompts;
- exhausted fidelity output records failure without a completion event;
- existing missing, malformed, extra, resegmented, passthrough, and orchestration retry behavior remains compatible.
