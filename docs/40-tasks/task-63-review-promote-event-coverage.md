# Task 63: Review/Promote Event Coverage

## Milestone

M63

## Depends On

M62

## Goal

Ensure glossary and idiom human-review and promotion commands emit structured operational events for lifecycle, artifact writes, and failures.

## Scope

- Add review lifecycle events for glossary and idiom review commands.
- Add artifact events for review JSON/CSV files.
- Add promotion artifact events for glossary candidates/conflicts and idiom candidates/policies/conflicts.
- Add failure events for review and promotion exceptions.
- Preserve CLI arguments, review file schemas, database behavior, and return payloads.

## Owned Files Or Modules

- `src/resemantica/glossary/pipeline.py`
- `src/resemantica/idioms/pipeline.py`
- Existing glossary, idiom, and CLI progress tests
- Event, glossary, idiom, task, and LLD documentation

## Interfaces

No command-line, database, review-file, or parser interfaces change.

New event families:

- `preprocess-glossary.review.*`
- `preprocess-glossary.promote.*`
- `preprocess-idioms.review.*`
- `preprocess-idioms.promote.*`

## Tests

- Existing review tests assert started, artifact-written, and completed events.
- Existing promotion tests assert artifact-written events and completed conflict counts.
- Failure tests assert `review.failed` and `promote.failed` events.
- CLI progress tests assert the generic artifact counter counts review/promote artifact events.

## Done Criteria

- Review and promote commands emit event-backed structured logs for lifecycle, artifacts, and failures.
- Stop handling remains unchanged.
- Documentation describes the event contract.
- Targeted tests and Ruff pass.
