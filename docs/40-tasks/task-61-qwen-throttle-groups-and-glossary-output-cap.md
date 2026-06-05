# Task 61: Qwen Throttle Groups And System Prompt

## Milestone

M61

## Depends On

M60

## Goal

Prevent in-process Qwen overload when multiple configured Qwen model IDs share a backend, and send the configured Qwen system prompt as a real OpenAI-compatible `system` message on every grouped Qwen request.

## Scope

- Add `llm.throttle_groups` config parsing and validation.
- Add optional `llm.throttle_groups.<name>.system_prompt` parsing and validation.
- Apply group semaphores in `LLMClient.generate_text()`.
- Keep exact-model semaphores and user-only requests for ungrouped models.
- Send `[system, user]` messages for grouped models with a non-empty `system_prompt`.
- Remove the glossary `translation_max_tokens` setting and stop capping glossary vote completions.
- Remove the Qwen glossary prompt line that invites reasoning.
- Update checked-in configs and operator documentation.

## Interfaces

- `LLMClient.generate_text(*, model_name, prompt, max_tokens=None)`
- `LLMClient.translate_glossary_candidate(...)`
- `[llm.throttle_groups.<name>] model_names`, `max_concurrent_requests`, `system_prompt`

## Tests

- Settings parse defaults and configured throttle groups.
- Settings parse, default, and validate throttle-group `system_prompt`.
- Settings reject empty groups, duplicate model membership, invalid limits, and non-string system prompts.
- LLM client serializes grouped model IDs while preserving ungrouped independence.
- LLM client sends `[system, user]` messages for grouped models with a system prompt.
- LLM client keeps user-only messages for ungrouped models.
- Glossary pipeline no longer passes a glossary `max_tokens` cap to candidate translation.

## Recovery Note

Existing bad Qwen glossary votes remain in SQLite. Regenerate them with `--force` or delete the targeted vote rows before rerunning the glossary translation stage.

## Done Criteria

- Checked-in configs group the Qwen analyst/eval models and include the Qwen system prompt.
- Glossary translation vote generation does not set the removed 64-token cap.
- Focused settings, LLM client, glossary, TUI, ruff, and pilot smoke checks pass.
