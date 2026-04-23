# Task 09: Pass 3 and Risk Handling

- **Milestone:** M9
- **Depends on:** M2, M8

## Goal

Implement Pass 3 readability polish and paragraph risk handling without weakening source fidelity, terminology, or structure constraints.

## Scope

In:

- paragraph risk classifier
- Pass 3 guarded readability pass
- high-risk skip or downgrade rules
- chapter-level validation for unresolved serious failures

Out:

- production orchestration controllers
- TUI presentation
- cleanup workflow

## Owned Files Or Modules

- `src/resemantica/translation/`
- `src/resemantica/llm/prompts/translate_pass3.txt`
- `tests/translation/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-09-pass3-and-risk.md`
- translation contracts in `../../DATA_CONTRACT.md`
- dependencies: M2 translation artifacts and M8 paragraph bundles

## Tests Or Smoke Checks

- risk-based Pass 3 skip behavior
- Pass 3 integrity validation catches terminology drift
- high-risk paragraph retains Pass 2 output
- chapter-level validation fails on unresolved structural or fidelity errors

## Done Criteria

- Pass 3 improves readability only within the documented guardrails
- high-risk paragraphs can skip Pass 3 safely
- Pass 3 never writes authority memory
- validation reports include risk class, retry count, and pass decisions
