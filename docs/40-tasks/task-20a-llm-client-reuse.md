# Task 20a: LLM Client Reuse

## Milestone And Depends On

Milestone: M20A

Depends on: M19

## Goal

Reuse the underlying OpenAI-compatible client instance across LLM calls so long runs avoid rebuilding the HTTP client for every prompt while preserving per-request stateless model context.

## Scope

In:
- Add lazy client caching inside `LLMClient`.
- Keep every `generate_text()` call as a fresh one-message request; do not retain prompt or response history.
- Add lightweight call metadata hooks or logs sufficient to confirm model call counts in tests.
- Document that client reuse does not accumulate context-window state.

Out:
- Changing model call order.
- Adding async or concurrent requests.
- Adding prompt-size guardrails or chunking.
- Changing OpenAI-compatible API payload shape.

## Owned Files Or Modules

- `src/resemantica/llm/client.py`
- `tests/llm/` or existing LLM client tests
- `docs/20-lld/lld-20a-llm-client-reuse.md`

## Interfaces To Satisfy

- `LLMClient.generate_text(model_name: str, prompt: str) -> str` remains unchanged.
- `LLMClient._build_openai_client()` is called at most once per `LLMClient` instance when no `generation_hook` is configured.
- `generation_hook` behavior remains unchanged and bypasses the OpenAI client.

## Tests Or Smoke Checks

- Unit test repeated `generate_text()` calls reuse one constructed OpenAI client.
- Unit test calls with different `model_name` values still send separate requests with only the current prompt.
- Unit test `generation_hook` path does not instantiate the OpenAI client.
- Run `uv run pytest tests/llm tests/translation tests/glossary tests/summaries tests/idioms tests/graph`.
- Run `uv run ruff check src tests`.

## Done Criteria

- LLM runtime calls reuse the client object within each `LLMClient` instance.
- No conversation history is stored or appended between calls.
- Existing public interfaces remain compatible.
- Tests prove reuse and stateless request behavior.
