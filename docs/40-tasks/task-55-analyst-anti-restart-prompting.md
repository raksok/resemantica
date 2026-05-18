# Task 55: Analyst Anti-Restart Prompting

## Milestone

M55

## Depends On

M54

## Goal

Keep deliberate analyst-model reasoning while reducing recursive restarts, repeated uncertainty loops, and narrated self-corrections in analyst-facing prompts.

## Scope

- Add prompt-local anti-restart instructions to analyst-facing prompts only.
- Preserve JSON-only, prose-only, schema, no-markdown, no-chain-of-thought, and `<think>` exclusion constraints already present in each prompt.
- Add uncertainty fallback wording that remains compatible with each prompt's schema.
- Bump edited prompt versions so cached analyst outputs are invalidated.
- Do not add system-message support in this slice.

## Owned Files Or Modules

- `src/resemantica/llm/prompts/summary_zh_structured.txt`
- `src/resemantica/llm/prompts/summary_zh_validate.txt`
- `src/resemantica/llm/prompts/summary_story_compact.txt`
- `src/resemantica/llm/prompts/glossary_evaluate.txt`
- `src/resemantica/llm/prompts/idiom_evaluate.txt`
- `src/resemantica/llm/prompts/graph_extract.txt`
- `src/resemantica/llm/prompts/translate_pass2.txt`
- `src/resemantica/llm/prompts/translate_pass3.txt`
- `tests/llm/test_analyst_prompt_policy.py`
- Affected prompt-version expectations in stage tests
- Task, LLD, and operations docs

## Interfaces To Satisfy

- Prompt rendering remains file-template based through `llm.prompts.load_prompt()` and `render_named_sections()`.
- Stage output schemas remain unchanged.
- Summary, glossary, idiom, graph, Pass 2, and Pass 3 parsers keep their current contracts.
- Prompt versions change only in edited analyst prompt files.

## Tests Or Smoke Checks

- Prompt regression tests assert anti-restart phrases are present.
- Prompt regression tests assert JSON/schema constraints remain present where applicable.
- Affected summaries, glossary evaluator, idiom evaluator, graph extraction, Pass 2, and Pass 3 tests pass.
- Ruff, mypy, and `git diff --check` pass.

## Done Criteria

- Analyst prompts instruct the model to reason through the task once, avoid restarting or looping over uncertainty, and return only the requested output.
- JSON prompts retain schema-valid uncertainty fallback behavior.
- Prose prompts retain final-prose-only behavior.
- Prompt version bumps invalidate stale analyst caches and checkpoints.
- No system-message API or prompt layering change is introduced.
