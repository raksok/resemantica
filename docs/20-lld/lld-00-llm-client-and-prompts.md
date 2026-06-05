# LLD 00: LLM Client and Prompts

## Summary

Define the shared LLM client, prompt loading, prompt versioning, named-section rendering, and embedding interface stub used by later milestones.

## Public Interfaces

Config fields:

- `llm.base_url`
- `llm.timeout_seconds`
- `llm.max_retries`
- `llm.context_window`
- `llm.max_concurrent_requests_per_model`
- `llm.throttle_groups.<group>.model_names`
- `llm.throttle_groups.<group>.max_concurrent_requests`
- `llm.throttle_groups.<group>.system_prompt`
- `models.translator_name`
- `models.analyst_name`
- `models.embedding_name`

Prompt contract:

- Analyst prompts must prefer compact schema-only responses and explicitly forbid prose, markdown, chain-of-thought, and `<think>` artifacts.
- Analyst prompts allow one deliberate reasoning pass but must discourage recursive restarts, repeated uncertainty loops, and narrated self-corrections; after one pass they must return only the requested output.
- JSON analyst prompts should tell uncertain models to choose the safest schema-valid value and return the required JSON shape without explaining uncertainty. Prose analyst prompts should choose the most evidence-supported wording and return only final prose.
- Prompt schemas are stage-owned interfaces; prompt optimization must not break existing parsers or artifact shapes.
- Prompt version bumps are required when prompt behavior changes so affected caches and checkpoints invalidate.
- Translator prompts are fragile and are excluded from the analyst prompt optimization pass unless a later task explicitly owns them.
- Prompt-local text remains the default contract for analyst behavior. Throttle groups may optionally attach a stateless per-request system message for backend-specific behavior.

Python modules:

- `llm.client.LLMClient`
- `llm.prompts.load_prompt()`
- `llm.prompts.render_named_sections()`
- `llm.tokens.count_tokens(text: str) -> int`
- `llm.embeddings.EmbeddingClient`

Prompt files:

- `src/resemantica/llm/prompts/translate_pass1.txt`
- `src/resemantica/llm/prompts/translate_pass2.txt`
- `src/resemantica/llm/prompts/translate_pass3.txt`
- `src/resemantica/llm/prompts/glossary_discover.txt`
- `src/resemantica/llm/prompts/glossary_translate.txt`
- `src/resemantica/llm/prompts/summary_zh_structured.txt`
- `src/resemantica/llm/prompts/summary_zh_short.txt`
- `src/resemantica/llm/prompts/summary_en_derive.txt`
- `src/resemantica/llm/prompts/summary_validate.txt`
- `src/resemantica/llm/prompts/idiom_detect.txt`
- `src/resemantica/llm/prompts/entity_extract.txt`
- `src/resemantica/llm/prompts/relationship_extract.txt`
- `src/resemantica/llm/prompts/translate_with_context.txt`
- `src/resemantica/llm/prompts/translate_with_term.txt`
- `src/resemantica/llm/prompts/translate_with_term_and_context.txt`

## Data Flow

1. Load model role names and llama.cpp router `base_url` from config.
2. Construct an OpenAI-compatible client using the `openai` Python package.
3. Send requests with `model=<configured_model_name>` so llama.cpp router mode selects the model.
4. Load prompt templates from package text files.
5. Read the inline `# version: ...` header and attach `prompt_version` to outputs and checkpoints.
6. Render prompt input through named sections using Python `str.format()`. Template files contain uppercase section names in curly braces (e.g., `{GLOSSARY}`, `{CONTEXT}`, `{SOURCE_TEXT}`, `{INSTRUCTIONS}`). The `render_named_sections(template, sections)` function raises `KeyError` on any missing section. No conditionals, loops, or nested expressions are supported in templates.
7. Keep embedding support behind an `llm/embeddings.py` interface stub until fuzzy retrieval is implemented.
8. Token counting uses tiktoken (Cl100k encoding) via `llm.tokens.count_tokens()`. This function is deterministic, offline, and does not require a running inference server. Packet assembly (M8) uses it for budget enforcement; the risk classifier (M9) uses it for context size estimation.
9. `LLMClient.generate_text()` applies a process-local semaphore before each OpenAI-compatible request. Ungrouped models use a semaphore keyed by exact `model_name`; by default, `llm.max_concurrent_requests_per_model = 1`, so same-model requests serialize across summaries, glossary, idioms, graph, packets, and translation. Different ungrouped model names have independent semaphores and may run concurrently.
10. `llm.throttle_groups` can assign multiple exact model names to one shared semaphore, for example Qwen analyst and eval model IDs backed by one local server. Grouped models use the group's `max_concurrent_requests` instead of the global per-model limit.
11. A throttle group can define `system_prompt`. Matching grouped models send that prompt as a `system` message followed by the per-call `user` prompt. Ungrouped models, and grouped models without a system prompt, keep the one-message user request shape.
12. `LLMClient.generate_text(..., max_tokens=None)` forwards `max_tokens` to the OpenAI-compatible request only when a caller supplies it.

## Validation Ownership

- `llm.prompts.load_prompt()` validates that every prompt file has a version header.
- Prompt rendering validates required named sections before calling the model.
- `LLMClient` owns retry limits, timeout handling, per-model and grouped request throttling, streaming support, token counting hooks, and structured output parsing.
- Stage-specific workflows own semantic validation of model output.

## Resume And Rerun

- Every model output artifact records model name and prompt version.
- Any prompt version change invalidates the affected pass or preprocessing artifact and downstream dependents.
- The client layer does not retain conversation memory; resumability is driven by persisted artifacts and checkpoints.

## Tests

- prompt version extraction from files
- named-section rendering with missing-section failure
- mocked OpenAI-compatible client request with configured model name
- per-model request throttling serializes same-model calls and allows different ungrouped model calls
- throttle-group request throttling serializes different model IDs in the same configured group
- throttle-group system prompt request shape sends `[system, user]`
- ungrouped request shape remains `[user]`
- `max_tokens` is omitted by default and forwarded when set
- prompt version recorded in checkpoint metadata
- embedding stub can be imported without requiring a live embedding backend
- `count_tokens()` returns deterministic counts for identical input
- `count_tokens()` handles Chinese, English, and mixed text

## Out Of Scope

- broad prompt rewrites that change stage schemas
- direct llama-cpp-python bindings
- framework wrappers around simple OpenAI-compatible calls
- conversation memory or retained message history
