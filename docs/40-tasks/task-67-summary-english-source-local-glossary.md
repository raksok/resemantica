# Task 67: Summary English Source-Local Glossary

## Milestone

M67

## Depends On

M66

## Goal

Prevent English summary derivation context overflows by rendering only locked
glossary entries that literally appear in the Chinese summary text being
translated.

## Scope

- Add shared source-local locked glossary selection for summary English derivation.
- Use the filtered context in `SUMMARY_EN_DERIVE`.
- Keep full locked glossary hashes for derived English provenance.
- Add prompt budget preflight before calling the translator model.
- Bump `summary_en_derive.txt` prompt version to `1.1`.
- Update focused tests and documentation.

## Owned Files Or Modules

- `src/resemantica/summaries/_context.py`
- `src/resemantica/summaries/derivation.py`
- `src/resemantica/summaries/pipeline.py`
- `src/resemantica/summaries/continuity.py`
- `src/resemantica/llm/prompts/summary_en_derive.txt`
- Summary and graph-continuity tests
- Manual, task, and LLD documentation

## Interfaces

No CLI flag, database schema, summary row shape, locked glossary schema, or graph
schema changes.

## Tests

- Summary derivation tests assert present locked terms are rendered and absent
  locked terms are omitted.
- Summary derivation tests assert prompt budget failures happen before LLM calls.
- Graph continuity tests assert `story_so_far_en_graph_compact` uses source-local
  glossary context while storing the full glossary hash.
- Prompt version expectations use `1.1`.

## Done Criteria

- `SUMMARY_EN_DERIVE` prompts use source-local locked glossary context.
- Derived English provenance hashes remain conservative.
- Targeted summary, graph-continuity, retry-failed orchestration, and Ruff checks pass.

