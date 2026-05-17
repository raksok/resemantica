# Task 50: Analyst Prompt Optimization

## Milestone

M50

## Depends On

M48, M49

## Goal

Reduce local analyst-model wall-clock time and redundant thinking output by tightening analyst-facing prompts while preserving schemas, artifacts, and translator prompt behavior.

## Scope

- Optimize summary analyst prompts for compact continuity output and validation warnings.
- Optimize Pass 2 analyst auditing so no-error responses do not echo unchanged draft text.
- Optimize graph, glossary evaluation, and idiom evaluation prompts for compact schema-only output.
- Keep translator prompts unchanged.
- Document a small before/after measurement loop using existing LLM usage and event metrics.

## Owned Files Or Modules

- `src/resemantica/llm/prompts/summary_zh_structured.txt`
- `src/resemantica/llm/prompts/summary_zh_validate.txt`
- `src/resemantica/llm/prompts/summary_story_compact.txt`
- `src/resemantica/llm/prompts/translate_pass2.txt`
- `src/resemantica/llm/prompts/graph_extract.txt`
- `src/resemantica/llm/prompts/glossary_evaluate.txt`
- `src/resemantica/llm/prompts/idiom_evaluate.txt`
- Stage LLDs and prompt documentation
- Focused translation parser tests

## Interfaces To Satisfy

- Prompt schemas remain compatible with existing parsers.
- Prompt version bumps invalidate affected caches and checkpoints.
- Pass 2 accepts the optimized no-error response shape: `fidelity_errors_found=false` with empty `corrected_text`.
- Older Pass 2 no-error responses with populated `corrected_text` remain safe because the parser ignores it.
- Translator prompt files are not changed.

## Tests Or Smoke Checks

- Pass 2 no-error response with empty `corrected_text` returns the original draft.
- Existing Pass 2 correction, fallback, and compatibility behavior remains green.
- Summary, graph, glossary, and idiom prompt parsers continue accepting schema-compatible responses.
- Focused stage tests and repo quality checks pass.

## Done Criteria

- Analyst prompts are compact and explicitly forbid prose/thinking artifacts.
- Summary prompts address the reported 107-chapter runtime bottleneck.
- Documentation records the prompt contract, measurement loop, and translator prompt exclusion.
- Targeted validation passes.
