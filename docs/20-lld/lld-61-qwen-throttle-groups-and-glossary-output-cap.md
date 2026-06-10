# LLD 61: Qwen Throttle Groups And System Prompt

## Summary

Add generic LLM throttle groups so multiple model IDs can share one process-local concurrency limit. Use this for Qwen variants that route to the same backend, and allow a throttle group to attach a stateless per-request system prompt to every model in that group.

The earlier 64-token glossary translation completion cap was reverted. Glossary vote generation now uses the normal request shape and does not pass a glossary-specific `max_tokens` value.

## Configuration

```toml
[llm.throttle_groups.qwen]
model_names = [
  "Qwen3.5-9B-GLM5.1",
  "Qwen3.5-9B-NonThinking-unsloth",
  "Qwopus3.5-9B",
  "Crow3.5-9B",
]
max_concurrent_requests = 1
system_prompt = "You are Qwen, created by Alibaba Cloud. You are a helpful assistant."
```

Rules:
- `llm.max_concurrent_requests_per_model` remains the default for ungrouped models.
- A configured throttle group uses one shared semaphore for all listed exact model names.
- Qwen-family fork model names such as `Qwopus3.5-9B` and `Crow3.5-9B` can be listed in the same group when they route to the same backend.
- `model_names` must be non-empty after trimming whitespace.
- `max_concurrent_requests` must be at least 1.
- `system_prompt` is optional and defaults to an empty string.
- A model name can appear in only one throttle group.

## LLM Client Behavior

`LLMClient.generate_text(..., max_tokens: int | None = None)` resolves group behavior before each provider request:

- grouped model: semaphore key is `group:<group_name>` and limit is the group's `max_concurrent_requests`.
- grouped model with non-empty `system_prompt`: sends `messages=[system, user]` for that request.
- grouped model with empty `system_prompt`: sends the existing one-message user request.
- ungrouped model: semaphore key is `model:<model_name>`, limit is `max_concurrent_requests_per_model`, and the request remains user-only.

The client remains stateless. It does not retain message history; a configured system prompt is included anew on each matching request.

`max_tokens` is still a generic optional provider argument for non-glossary callers that explicitly need it. Glossary translation no longer supplies a glossary completion cap.

## Glossary Translation Behavior

`translate_glossary_candidates()` no longer passes `config.glossary.translation_max_tokens` to glossary vote generation. The `glossary.translation_max_tokens` setting was removed from config.

The Qwen-specific glossary translation prompt keeps the stricter prompt cleanup: the prior line that invited reasoning before the final line remains removed, and the prompt version remains bumped.

## Out Of Scope

- Cross-process locks.
- Per-stage throttle groups.
- Strict garbage-output validation beyond existing glossary cleaning.
