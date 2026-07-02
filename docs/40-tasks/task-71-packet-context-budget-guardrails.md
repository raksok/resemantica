# Task 71: Packet Context Budget Guardrails

## Milestone

M71

## Depends On

M70

## Goal

Prevent packet and bundle context growth from producing oversized translation
prompts in long releases.

## Scope

- Bound packet graph context before packet artifact write.
- Count all prompt-relevant packet fields in packet budget enforcement.
- Use `[packets]` budget settings for packet and bundle limits.
- Add final Pass 1, Pass 2, and Pass 3 prompt budget checks.
- Bump packet builder version so old packet artifacts rebuild.

## Interfaces To Satisfy

- `packets.builder.enrich_with_graph_context(..., max_graph_tokens=...)`
- `packets.invalidation.detect_stale_packet(..., packet_builder_version=...)`
- `translation.pass1.translate_pass1(..., config=None, chapter_number=None)`
- `translation.pass2.translate_pass2(..., config=None)`
- `translation.pass3.translate_pass3(..., config=None, chapter_number=None)`

## Tests Or Smoke Checks

- `uv run --extra dev pytest tests\packets -q`
- `uv run --extra dev pytest tests\translation -q`
- `uv run --extra dev pytest tests\orchestration\test_orchestration.py -q -k "retry_failed or RetryFailed"`
- `uv run --extra dev ruff check src\resemantica\packets src\resemantica\translation tests\packets tests\translation tests\orchestration\test_orchestration.py`

## Done Criteria

- Packet graph sections are bounded and deterministic.
- Packet artifacts rebuild when builder-version semantics change.
- Translation budget failures occur before LLM calls.
- Focused packet, translation, orchestration retry, and Ruff checks pass.
