# Task 79: Pass1 Mixed-Language Candidate Repair

## Milestone

M79

## Depends On

M78

## Goal

Recover a mostly-English Pass 1 response that retains Chinese text without discarding the valid draft or increasing the existing content-attempt limit.

## Scope

- Separate response formatting cleanup from untranslated-Chinese detection.
- When a non-empty candidate contains Chinese, include the candidate and its exact Chinese spans in the next same-model correction prompt.
- Replace the prior candidate with the latest candidate on each retry.
- Keep empty-response retries, strict English-only acceptance, and resegmentation fallback behavior.
- Preserve precise final rejection reasons through parent and child Pass 1 artifacts.

## Owned Files Or Modules

- `src/resemantica/translation/pass1.py`
- `src/resemantica/translation/pipeline.py`
- Pass 1 cleaning, prompt-budget, chapter translation, and orchestration tests
- translation LLD and task index

## Interfaces To Satisfy

- `translate_pass1(...) -> str` remains compatible.
- CLI arguments, configuration, checkpoint identity, and artifact schemas remain unchanged.
- The base Pass 1 prompt version remains unchanged so compatible successful block mappings remain reusable.
- Content generation remains bounded to the initial request plus two retries.
- Pass 2 receives only non-empty, English-only Pass 1 output.

## Tests Or Smoke Checks

- `uv run --extra dev pytest tests\translation tests\orchestration -q`
- `uv run --extra dev ruff check src\resemantica tests`
- `uv run --extra dev mypy src\resemantica`

## Done Criteria

- The observed chapter-422 response containing `桐叶` is repaired using the prior candidate before resegmentation.
- Empty responses retain the existing generic correction behavior.
- Repeated mixed-language failure reports the remaining Chinese spans.
- Failed resegmentation reports each failed child ID and reason.
- Correction prompts remain subject to the Pass 1 token budget.
- Existing long- and short-block resegmentation, placeholder, and partial-cache tests remain green.

## Run 001 Recovery

After deploying M79, preview and execute repair for chapter 422:

```powershell
uv run rsem run retry-failed -r 1 -R 001 -c resemantica-pilot.toml -t translate-range -s 422 -e 422 -n
uv run rsem run retry-failed -r 1 -R 001 -c resemantica-pilot.toml -t translate-range -s 422 -e 422
```

The repair must reuse compatible successful Pass 1 blocks, regenerate failed block `ch422_blk085`, reject any remaining Chinese output, and complete the chapter translation checkpoint before the production run resumes.
