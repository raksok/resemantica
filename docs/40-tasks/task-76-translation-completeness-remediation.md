# Task 76: Translation Completeness Remediation

## Milestone

M76

## Depends On

M75

## Goal

Prevent incomplete Pass 1 artifacts from advancing and repair existing Run 001 artifacts at block granularity.

## Scope

- Preserve punctuation and placeholder-only blocks without model calls.
- Retry empty or Chinese-bearing Pass 1 output twice with an English-only correction.
- Reuse successful Pass 1 and Pass 2 blocks while repairing missing blocks.
- Reject incomplete or malformed translation mappings before Pass 2 and EPUB rebuild.
- Preserve the production run checkpoint during `retry-failed` repair execution.

## Owned Files Or Modules

- `src/resemantica/translation`
- `src/resemantica/orchestration`
- `src/resemantica/epub`
- translation, orchestration, and EPUB tests

## Interfaces To Satisfy

- Existing artifact fields and CLI flags remain compatible.
- Pass 3 remains optional.
- Every extracted block has a non-empty final output before rebuild.

## Tests Or Smoke Checks

- `uv run --extra dev pytest tests\translation tests\orchestration tests\epub -q`
- `uv run --extra dev ruff check src\resemantica tests`
- `uv run --extra dev mypy src\resemantica`

## Done Criteria

- Failed Pass 1 blocks cannot be skipped by Pass 2.
- Partial artifacts resume without regenerating successful blocks.
- Translation and rebuild completeness gates reject one missing block.
- Repair execution restores the original production checkpoint.

## Run 001 Recovery

After deploying this milestone, preview and execute the block-level repair, verify zero failed translation checkpoints and exact final block coverage, then resume production:

```powershell
uv run rsem run retry-failed -r 1 -R 001 -c resemantica-pilot.toml -t translate-range -n
uv run rsem run retry-failed -r 1 -R 001 -c resemantica-pilot.toml -t translate-range
uv run rsem run resume -r 1 -R 001 -c resemantica-pilot.toml
```

EPUB rebuild must not begin until the completeness gate passes with no `paragraph_skipped` events attributable to failed Pass 1 blocks.
