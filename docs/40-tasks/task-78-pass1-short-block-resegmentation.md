# Task 78: Pass1 Short-Block Resegmentation Recovery

## Milestone

M78

## Depends On

M77

## Goal

Recover a short Pass 1 block when the translator exhausts its content retries but the source can be safely divided at a clause boundary.

## Scope

- Preserve the existing sentence-based resegmentation path for long blocks.
- When structural validation fails and sentence resegmentation yields one segment, split at the safe Chinese or ASCII clause boundary nearest the source midpoint.
- Preserve punctuation, segment order, and exact source reconstruction.
- Keep placeholder-bearing and safely unsplittable blocks on the existing failure path.
- Include failed block IDs and validation reasons in orchestration errors.

## Owned Files Or Modules

- `src/resemantica/translation/pipeline.py`
- `src/resemantica/orchestration/runner.py`
- translation and batched orchestration tests
- translation LLD and task index

## Interfaces To Satisfy

- Existing CLI arguments, configuration, artifact schemas, and checkpoint schemas remain unchanged.
- Successful cached blocks remain reusable during repair.
- Pass 2 starts only after every Pass 1 block succeeds.
- Failed recovery remains a hard stop rather than advancing incomplete output.

## Tests Or Smoke Checks

- `uv run --extra dev pytest tests\translation tests\orchestration -q`
- `uv run --extra dev ruff check src\resemantica tests`
- `uv run --extra dev mypy src\resemantica`

## Done Criteria

- A short clause-delimited block can recover after its full-block content retries are exhausted.
- Segment sources concatenate exactly to the original source.
- Placeholder-bearing and unsplittable failures do not enter clause resegmentation.
- Single-chapter and batched errors identify failed blocks and their validation reasons.
- Existing long-block resegmentation and partial artifact repair tests remain green.

## Run 001 Recovery

After deploying M78, preview and execute repair for chapter 405, then resume the production range:

```powershell
uv run rsem run retry-failed -r 1 -R 001 -c resemantica-pilot.toml -t translate-range -s 405 -e 405 -n
uv run rsem run retry-failed -r 1 -R 001 -c resemantica-pilot.toml -t translate-range -s 405 -e 405
uv run rsem run resume -r 1 -R 001 -c resemantica-pilot.toml
```

The repair must reuse successful Pass 1 blocks, regenerate only failed block `ch405_blk017`, and leave chapter 405 with a successful translation checkpoint before production resumes.
