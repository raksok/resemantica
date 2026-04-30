# Task 20b: Prompt Budget Guardrails + Long-Chapter Chunking

## Milestone And Depends On

Milestone: M20B

Depends on: M20A

## Goal

Prevent preprocessing prompts from exceeding configured model budgets by adding shared prompt-size checks and chunking long chapter inputs for whole-chapter preprocessing stages.

## Scope

In:
- Add a shared prompt budget helper using `llm.tokens.count_tokens()`.
- Enforce `budget.max_context_per_pass` for preprocessing prompts before LLM submission.
- Split long chapter source text into deterministic chunks for glossary discovery, summary generation/validation, idiom detection, and graph extraction.
- Merge chunk-level outputs into the same existing candidate, summary, idiom, and graph models.
- Emit clear skip/failure events when a prompt cannot be made budget-safe.

Out:
- Changing translation pass order.
- Changing prompt semantics beyond adding chunk metadata.
- Replacing packet budget logic.
- Adding parallel LLM calls.

## Owned Files Or Modules

- `src/resemantica/llm/`
- `src/resemantica/glossary/discovery.py`
- `src/resemantica/summaries/`
- `src/resemantica/idioms/extractor.py`
- `src/resemantica/graph/extractor.py`
- `tests/`
- `docs/20-lld/lld-20b-prompt-budget-and-long-chapter-chunking.md`

## Interfaces To Satisfy

- Add `llm.budget.ensure_prompt_within_budget(prompt: str, *, config: AppConfig, stage_name: str, chapter_number: int | None = None) -> None`.
- Add deterministic chunking helper returning ordered chunks with `chunk_index`, `chunk_count`, and source text.
- Existing pipeline function signatures remain compatible.
- Existing artifact schemas remain compatible; chunk metadata may be added under optional metadata fields only.

## Tests Or Smoke Checks

- Unit test budget helper accepts under-budget prompts and rejects over-budget prompts with a readable error.
- Unit test long chapter text is chunked deterministically and preserves ordering.
- Pipeline tests cover glossary/idiom/graph extraction over multi-chunk input.
- Summary test covers long chapter chunking without exceeding budget.
- Run `uv run pytest tests/glossary tests/summaries tests/idioms tests/graph tests/llm`.
- Run `uv run ruff check src tests`.

## Done Criteria

- Whole-chapter preprocessing prompts are checked before submission.
- Long chapters are processed through bounded chunks rather than one oversized prompt.
- Existing downstream DB rows and JSON artifacts remain readable by current code.
- Tests cover over-budget failure and successful chunked processing.
