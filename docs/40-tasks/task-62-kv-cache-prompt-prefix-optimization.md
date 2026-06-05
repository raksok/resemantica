# Task 62: KV-Cache Prompt Prefix Optimization

## Milestone

M62

## Depends On

M61

## Goal

Improve KV-cache reuse for selected non-HY-MT preprocessing and translation-audit prompts by moving volatile per-call inputs to the end of each prompt while preserving output contracts and parser behavior.

## Scope

- Reorder the stable task instructions, strict rules, and output schemas before dynamic input blocks.
- Bump versions for the eight edited prompt files.
- Preserve existing placeholders and section headers needed by prompt rendering and test doubles.
- Keep prompt rendering code, parser schemas, LLM client behavior, cache storage, and HY-MT prompt files unchanged.
- Clarify prompt-contract docs so the fragile translator-prompt constraint applies to HY-MT-specific prompt patterns, not these selected prompts.

## Owned Files Or Modules

- `src/resemantica/llm/prompts/glossary_translate_gemma.txt`
- `src/resemantica/llm/prompts/glossary_evaluate.txt`
- `src/resemantica/llm/prompts/idiom_evaluate.txt`
- `src/resemantica/llm/prompts/idiom_detect.txt`
- `src/resemantica/llm/prompts/idiom_meaning.txt`
- `src/resemantica/llm/prompts/graph_extract.txt`
- `src/resemantica/llm/prompts/translate_pass2.txt`
- `src/resemantica/llm/prompts/translate_pass3.txt`
- `tests/llm/test_analyst_prompt_policy.py`
- Affected prompt-version expectations in stage tests
- Task and LLD documentation

## Interfaces

- Prompt templates still render with the existing `str.format()` placeholder contract.
- JSON prompts keep their current schema, no-markdown, no-chain-of-thought, and `<think>` exclusion constraints.
- Translator-facing Gemma glossary and idiom meaning prompts still return plain English text only.
- Pass 2 still returns the existing JSON object contract.
- Pass 3 still returns final polished prose only.
- Prompt version bumps naturally invalidate affected caches, checkpoints, drafts, and vote artifacts keyed by prompt version.

## Tests

- Prompt policy tests assert existing schema and anti-restart constraints.
- Prompt policy tests assert dynamic placeholders appear after stable rules or schemas.
- Glossary, idiom, graph, and translation stage tests continue passing with the updated prompt versions.
- Ruff passes for `src/resemantica` and `tests`.

## Done Criteria

- The eight prompt files use stable prefixes before dynamic inputs.
- HY-MT prompt files remain untouched.
- Documentation captures the cache-prefix rationale and prompt-contract clarification.
- Targeted validation passes.
