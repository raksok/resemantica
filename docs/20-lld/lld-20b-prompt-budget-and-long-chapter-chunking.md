# LLD 20b: Prompt Budget Guardrails And Long-Chapter Chunking

## Summary

Add shared prompt budget checks and deterministic long-chapter chunking for preprocessing pipelines that currently submit whole-chapter prompts.

## Problem Statement

Settings define `llm.context_window` and `budget.max_context_per_pass`, but only packet assembly enforces token budgets. Glossary discovery, summary generation/validation, idiom detection, and graph extraction can construct prompts from an entire long chapter and exceed a 65k context model.

## Technical Design

Add `src/resemantica/llm/budget.py`:

```python
@dataclass(slots=True)
class PromptBudgetError(ValueError):
    stage_name: str
    chapter_number: int | None
    token_count: int
    max_tokens: int

def ensure_prompt_within_budget(
    prompt: str,
    *,
    config: AppConfig,
    stage_name: str,
    chapter_number: int | None = None,
) -> int: ...
```

The helper counts tokens with `count_tokens(prompt)` and rejects prompts above `config.budget.max_context_per_pass`. It returns the token count for metrics or artifact metadata.

Add deterministic chunking:

```python
@dataclass(slots=True)
class TextChunk:
    chunk_index: int
    chunk_count: int
    text: str

def chunk_text_for_prompt(
    text: str,
    *,
    config: AppConfig,
    static_prompt_tokens: int,
) -> list[TextChunk]: ...
```

Chunking should prefer paragraph/newline boundaries, then sentence punctuation, then character slicing as a fallback. Chunks must preserve source order.

## Pipeline Behavior

- Glossary, idiom, and graph extractors process each chunk and merge resulting rows with existing normalization/deduplication behavior.
- Summaries generate chunk summaries first when the whole-chapter prompt is over budget, then combine chunk summaries into the current structured summary shape with a final budget-checked prompt.
- Validation prompts are also budget-checked; if a validation prompt cannot fit, fail the chapter with a clear `prompt_budget_exceeded` reason.
- Pipelines emit `*.chapter_skipped` or validation failure events when a chapter cannot be made budget-safe.

## Artifact Compatibility

Existing artifact schemas remain readable. Optional metadata may include:

```json
{
  "chunking": {
    "chunk_count": 3,
    "max_context_per_pass": 49152
  }
}
```

## Tests

- Budget helper under-limit and over-limit tests.
- Chunking preserves order and never emits empty chunks.
- Extractors merge multi-chunk candidates/entities without duplicate inflation.
- Summary pipeline handles a forced-low budget with chunked generation.

## Out Of Scope

- Packet budget replacement.
- Parallel chunk processing.
- Translation range model batching.

## Implementation Notes

- Shared helpers live in `resemantica.llm.budget`.
- Whole-chapter preprocessing stages budget-check prompts before calling the model.
- Long chapter source text is processed as ordered chunks for glossary discovery, summaries, idiom detection, and graph extraction.
- Summary chunk outputs are merged deterministically into the existing structured summary shape before existing validation and artifact writes.
