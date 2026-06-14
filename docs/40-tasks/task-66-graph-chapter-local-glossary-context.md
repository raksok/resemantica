# Task 66: Graph Chapter-Local Glossary Context

## Milestone

M66

## Depends On

M65

## Goal

Reduce graph extraction prompt size by sending only graph-relevant locked glossary entries that literally appear in the current chapter source text, while preserving deterministic locked glossary matching after LLM extraction.

## Scope

- Keep the full graph-relevant locked glossary in Python for post-LLM matching.
- Build `GLOSSARY_CONTEXT` per chapter after source text is loaded.
- Include only entries where `entry.source_term in source_text`.
- Keep `(none)` as the fallback prompt context.
- Bump `graph_extract.txt` prompt version to `2.4`.
- Update graph docs and focused tests.

## Owned Files Or Modules

- `src/resemantica/graph/extractor.py`
- `src/resemantica/llm/prompts/graph_extract.txt`
- `tests/graph/test_graph_pipeline.py`
- Manual, task, and LLD documentation

## Interfaces

No database schema, graph node shape, locked glossary schema, LadybugDB table, or CLI flag changes.

## Tests

- Graph pipeline tests assert chapter-local glossary rendering.
- Graph pipeline tests assert absent locked terms are not included in the chapter prompt.
- Graph pipeline tests assert matched extracted entities still resolve to locked glossary target/canonical names.
- Draft prompt version expectations use `2.4`.

## Done Criteria

- Graph prompts include only chapter-local locked glossary context.
- Existing graph matching and storage behavior remain unchanged.
- Targeted graph, retry-failed orchestration, and Ruff checks pass.

