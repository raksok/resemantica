# LLD 57: Summary Validation Gates

## Summary

LLM summary-content validation is a hard gate. A summary attempt is acceptable only when deterministic validation passes and `summary_zh_validate.txt` returns an empty `flags` list. Non-empty `warnings` remain review notes only.

## Severity Matrix

| Validator output | Severity | Action |
|------------------|----------|--------|
| `unsupported_claim` | fatal | retry attempt |
| `major_omission` | fatal | retry attempt |
| `wrong_referent` | fatal | retry attempt |
| `premature_reveal` | fatal | retry attempt |
| `ambiguity_overwritten` | fatal | retry attempt |
| `<parse_error>` | fatal | retry attempt |
| unknown flag string | fatal | retry attempt |
| `warnings` only | non-fatal | persist as artifact review notes |

## Data Flow

1. `generate_chapter_summary()` generates and parses a structured Chinese summary.
2. Deterministic schema and future-knowledge validation runs.
3. The summaries pipeline supplies a content-validation callback using `summary_zh_validate.txt`.
4. Any returned `flags` become `llm_content_validation_failed` attempt errors.
5. Retry feedback includes the flags and targeted correction hints.
6. Only an attempt with empty flags can persist approved structured and short rows.

## Failure Modes

When retries exhaust for content validation:

- `summary_drafts.validation_status` is `failed`.
- draft JSON records `failure_category = "llm_content_validation_failed"`, validation errors, hints, and final flags.
- `validated_summaries_zh` stores failed `chapter_summary_zh_structured` and `chapter_summary_zh_short` rows for audit.
- `story_so_far_*` rows are not built for that chapter.
- summary checkpoints do not advance past the failed chapter.
- `preprocess-summaries.chapter_failed` is emitted with severity `error`.

## Audit Rows

Repository read helpers are approved-only by default. Consumers that build runtime context use only approved rows. Audit tools may pass `validation_status=None` to inspect failed rows explicitly.

## Events

Each flagged validation attempt emits one aggregated `preprocess-summaries.llm_validation_warning` event with:

- `flags`
- `flag_count`
- `attempt_number`
- `action`: `retry` or `fail`

Validator `warnings` are not warning events.

## Downstream Gates

Packets, graph continuity, stage gates, and retry planning must treat failed validated rows as missing runtime inputs. Failed rows are evidence, not continuity.
