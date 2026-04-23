# LLD 00: LLM Client and Prompts

## Summary

Define the shared LLM client, prompt loading, prompt versioning, named-section rendering, and embedding interface stub used by later milestones.

## Public Interfaces

Config fields:

- `llm.base_url`
- `llm.timeout_seconds`
- `llm.max_retries`
- `llm.context_window`
- `models.translator_name`
- `models.analyst_name`
- `models.embedding_name`

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

## Validation Ownership

- `llm.prompts.load_prompt()` validates that every prompt file has a version header.
- Prompt rendering validates required named sections before calling the model.
- `LLMClient` owns retry limits, timeout handling, streaming support, token counting hooks, and structured output parsing.
- Stage-specific workflows own semantic validation of model output.

## Resume And Rerun

- Every model output artifact records model name and prompt version.
- Any prompt version change invalidates the affected pass or preprocessing artifact and downstream dependents.
- The client layer does not retain conversation memory; resumability is driven by persisted artifacts and checkpoints.

## Tests

- prompt version extraction from files
- named-section rendering with missing-section failure
- mocked OpenAI-compatible client request with configured model name
- prompt version recorded in checkpoint metadata
- embedding stub can be imported without requiring a live embedding backend
- `count_tokens()` returns deterministic counts for identical input
- `count_tokens()` handles Chinese, English, and mixed text

## Out Of Scope

- prompt text quality iteration
- direct llama-cpp-python bindings
- framework wrappers around simple OpenAI-compatible calls
