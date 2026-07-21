# Task 80: Pass1 Mixed-Language Pass2 Handoff

## Milestone

M80

## Depends On

M79

## Goal

Preserve a usable mostly-English Pass 1 draft when its final correction still contains isolated Chinese spans, then make Pass 2 remove those spans before translation can continue.

## Scope

- Keep the initial Pass 1 request and two same-model correction retries.
- After those attempts, defer a non-empty candidate containing both Latin letters and Chinese spans to Pass 2.
- Keep empty and fully Chinese candidates on the existing failure and resegmentation paths.
- Record deferred spans in Pass 1 block or segment artifacts and validation warnings.
- Treat Chinese remaining in a Pass 2 draft or correction as a retryable fidelity error.
- Fail Pass 2 after its configured validation retries if any Chinese spans remain.

## Owned Files Or Modules

- `src/resemantica/translation/pass1.py`
- `src/resemantica/translation/pipeline.py`
- `src/resemantica/translation/validators.py`
- single and batch Pass 2 prompts
- translation tests and translation LLD

## Interfaces To Satisfy

- `translate_pass1(...) -> str` keeps its signature and returns the latest eligible mixed candidate after retry exhaustion.
- Pass 1 artifacts may include `untranslated_chinese_spans` on a block or resegmented child.
- Pass 2 prompt versions advance so prior Pass 2 checkpoints are not reused under the stricter contract.
- CLI arguments and translation configuration remain unchanged.

## Decision Log

- Defer only after both existing Pass 1 correction retries, rather than bypassing the translator model's repair opportunity.
- Defer only mixed Latin/Chinese drafts; do not turn Pass 2 into the primary translator for fully Chinese responses.
- Keep the final output gate strict: remaining Chinese fails Pass 2 instead of being forwarded to Pass 3.
- Reuse the configured Pass 2 validation retry budget instead of adding another retry setting.

## Tests Or Smoke Checks

- `uv run --extra dev pytest tests\translation tests\orchestration -q`
- `uv run --extra dev ruff check src\resemantica tests`
- `uv run --extra dev mypy src\resemantica`

## Done Criteria

- The observed chapter-422-shaped `桐叶` candidate reaches Pass 2 without resegmentation after Pass 1 correction exhaustion.
- Pass 2 repairs the deferred span and emits English-only output.
- A model response that declares the mixed draft faithful is rejected deterministically and retried.
- Retry exhaustion reports the exact remaining Chinese spans and fails the block.
- Batch validation falls back only mixed blocks that require repair.
- Existing empty, fully Chinese, placeholder, resegmentation, cache, and orchestration behavior remains green.

## Run 001 Recovery

After deploying M80, preview and execute chapter 422 repair:

```powershell
uv run rsem run retry-failed -r 1 -R 001 -c resemantica-pilot.toml -t translate-range -s 422 -e 422 -n
uv run rsem run retry-failed -r 1 -R 001 -c resemantica-pilot.toml -t translate-range -s 422 -e 422
```

The retry must reuse compatible successful Pass 1 blocks, preserve the latest mixed draft for `ch422_blk085`, and stop if Pass 2 cannot remove every remaining Chinese span.
