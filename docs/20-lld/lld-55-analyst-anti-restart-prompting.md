# LLD 55: Analyst Anti-Restart Prompting

## Summary

Analyst-facing prompts now use prompt-local instructions to bound reasoning behavior. The policy allows a single deliberate reasoning pass, then requires the model to return the requested output without recursive restarts, repeated uncertainty loops, or narrated self-corrections.

## Prompt Policy

Step-by-step internal reasoning is allowed. The target behavior is not instant answering; it is one focused pass followed by the stage's required output.

Recursive restart patterns are discouraged. Prompts explicitly tell the model not to restart reasoning, loop over the same uncertainty, or narrate self-corrections such as "but wait", "let me rethink", or "I should check again".

JSON prompts add a schema-safe uncertainty fallback. If uncertainty remains after one pass, the model chooses the safest schema-valid value and returns the required JSON shape without explaining uncertainty. Array-schema prompts keep array wording.

Prose prompts add a prose-safe uncertainty fallback. If uncertainty remains after one pass, the model chooses the most evidence-supported wording and returns only the final requested prose.

## Design Choice

This slice uses prompt-local instructions rather than adding system-message support. That keeps the change scoped to analyst prompt files and avoids altering the shared LLM client API, retry behavior, or prompt rendering contract.

## Cache Behavior

Every edited prompt bumps its inline `# version: ...` header. Existing caches, checkpoints, graph extraction drafts, and translation artifacts keyed by prompt version become stale naturally through the current versioning mechanism.

## Affected Prompts

- `summary_zh_structured.txt`
- `summary_zh_validate.txt`
- `summary_story_compact.txt`
- `glossary_evaluate.txt`
- `idiom_evaluate.txt`
- `graph_extract.txt`
- `translate_pass2.txt`
- `translate_pass3.txt`

## Tests

- Prompt-policy regression tests assert the anti-restart wording across analyst prompts.
- JSON prompt tests assert existing JSON-only and schema constraints remain visible.
- Stage suites cover summaries, glossary evaluation, idiom evaluation, graph extraction, Pass 2, and Pass 3 behavior.
