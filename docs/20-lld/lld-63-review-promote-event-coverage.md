# LLD 63: Review/Promote Event Coverage

## Summary

Glossary and idiom review/promote commands now emit structured events for operator-visible lifecycle, artifact writes, and failures. Events use the existing pipeline-local `_emit()` wrappers, so they are persisted in tracking and mirrored to structured Loguru JSONL records through `emit_event()`.

No CLI flags, review file formats, database schemas, parser behavior, or promotion validation rules change.

## Event Contract

Glossary review emits:

- `preprocess-glossary.review.started`
- `preprocess-glossary.review.json.artifact_written`
- `preprocess-glossary.review.csv.artifact_written`
- `preprocess-glossary.review.completed`
- `preprocess-glossary.review.failed`

Glossary promotion emits:

- existing `preprocess-glossary.promote.started`
- `preprocess-glossary.promote.candidates.artifact_written`
- `preprocess-glossary.promote.conflicts.artifact_written`
- existing `preprocess-glossary.promote.completed`
- `preprocess-glossary.promote.failed`

Idiom review emits:

- `preprocess-idioms.review.started`
- `preprocess-idioms.review.json.artifact_written`
- `preprocess-idioms.review.csv.artifact_written`
- `preprocess-idioms.review.completed`
- `preprocess-idioms.review.failed`

Idiom promotion emits:

- existing `preprocess-idioms.promote.started`
- `preprocess-idioms.promote.candidates.artifact_written`
- `preprocess-idioms.promote.policies.artifact_written`
- `preprocess-idioms.promote.conflicts.artifact_written`
- existing `preprocess-idioms.promote.completed`
- `preprocess-idioms.promote.failed`

## Payloads

Review artifact events include `artifact_path`, `artifact_format`, and `entries_written`.

Review completion includes `entries_written`, `review_path`, `review_json_path`, and `review_csv_path`.

Promotion artifact events include `artifact_path`, `artifact_format`, and the relevant count field: `candidate_count`, `policy_count`, or `conflict_count`.

Promotion completion keeps existing `promoted_count` and includes `conflict_count`.

Failure events use `severity = "error"` and include `phase`, `error`, and a human-readable message.

## Stop Boundary

`StopRequested` remains separate from failure handling. Review/promote failure events are for unexpected exceptions; stop handling remains owned by the current CLI/orchestration stop path.

## Validation

- Glossary and idiom pipeline tests cover review lifecycle, artifact, completed, and failed events.
- Promotion tests cover artifact and failed events.
- CLI progress tests cover generic artifact counting.
- Existing review file content and promotion behavior assertions remain unchanged.
