# LLD 20a: LLM Client Reuse

## Summary

Reuse the underlying OpenAI-compatible client per `LLMClient` instance. This removes repeated client construction overhead while keeping each generation request stateless and context-window independent.

## Problem Statement

`LLMClient.generate_text()` currently calls `_build_openai_client()` for every prompt. On long runs this rebuilds the API client thousands of times. That overhead is avoidable and unrelated to model context. Reusing the client should not append previous prompts because each call still sends a fresh `messages=[{"role": "user", "content": prompt}]` payload.

## Technical Design

Add a private cached client field to `LLMClient`:

```python
_openai_client: Any | None = field(default=None, init=False, repr=False)
```

Add a helper:

```python
def _get_openai_client(self) -> Any:
    if self._openai_client is None:
        self._openai_client = self._build_openai_client()
    return self._openai_client
```

`generate_text()` uses `_get_openai_client()` when `generation_hook` is `None`. The hook path continues to return `generation_hook(model_name, prompt)` and must not create the OpenAI client.

## Context Window Contract

Client reuse does not store prompt history. Each request must still pass only the current prompt:

```python
messages=[{"role": "user", "content": prompt}]
```

No conversation state, previous responses, or prior prompts are retained in `LLMClient`.

## Tests

- Patch `_build_openai_client()` and assert two `generate_text()` calls build one client.
- Assert generated API calls include only the current prompt.
- Assert calls with two different model names reuse the same client object but send the requested model name.
- Assert `generation_hook` bypasses `_build_openai_client()`.

## Out Of Scope

- Request batching.
- Async execution.
- Prompt budget enforcement.
- Model-grouped orchestration.

## Implementation Notes

- `LLMClient` now lazily caches the OpenAI-compatible client with `_get_openai_client()`.
- `generation_hook` still bypasses OpenAI client construction.
- `generate_text()` still submits exactly one user message per call, so client reuse does not accumulate model context.
