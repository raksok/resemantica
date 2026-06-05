# LLD 05: Idioms Workflow

## Summary

Detect idioms and set phrases, capture their meaning and preferred English rendering, and store them as authoritative structured assets for packet assembly and translation support.

Update: LLM-first idiom detection is superseded by `lld-41-deterministic-idiom-discovery.md`. Translation, review, promotion, exact-match policy lookup, and packet consumption remain owned by this LLD.

Post-MVP additions: human-override review workflow, cross-chapter deduplication via UNIQUE constraint, translation response post-processing, and improved detect prompt.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli preprocess idioms --release <release_id>`
- `uv run python -m resemantica.cli preprocess idiom-review --release <release_id>`
- `uv run python -m resemantica.cli preprocess idiom-promote --release <release_id> [--review-file <path>]`

Python modules:

- `idioms.extractor.extract_idioms()`
- `idioms.matching.match_idioms()`
- `idioms.validators.validate_idiom_policy()`
- `idioms.repo.IdiomRepository`
- `idioms.pipeline.review_idiom_candidates()`

SQLite datasets:

- `idiom_candidates` (includes `UNIQUE (release_id, normalized_source_text)` constraint)
- `idiom_policies`
- `idiom_conflicts`

## Data Flow

1. Read extracted chapter text.
2. Use `analyst_name` model to detect candidate idioms and set phrases.
3. Capture Chinese meaning and propose English rendering policy.
4. **Upsert** with merge — same normalized idiom across chapters is deduplicated (appearance_count summed, chapter ranges merged).
5. Perform deterministic normalization and duplicate detection.
6. **Optional human review** — `idiom-review` writes translated candidates to JSON and CSV review files. User edits renderings, meanings, marks entries for deletion, or adds new entries. `idiom-promote --review-file` reads the edited file.
7. Promote validated idioms into the authoritative idiom store.
8. Provide exact-match lookup for packet assembly.

Analyst prompt optimization applies only to the deterministic idiom evaluator documented in LLD 41. Idiom translation and meaning prompts are translator-facing and are intentionally out of scope for M50.

## Detect Prompt (`llm/prompts/idiom_detect.txt`)

The prompt instructs the LLM to identify Chinese idioms (成语、惯用语) from chapter text. v2.0 adds:

- Explicit requirement that `source_text` is the idiom phrase only (e.g. `"孤苦伶仃"`, not the full sentence)
- Exclusion guidance (dates, common expressions, descriptive phrases are not idioms)

## Translation Response Post-Processing

Both LLM calls in translation phase (rendering + meaning) apply cleanup:
- Strip common label prefixes (`Category:`, `Translation:`, `Evidence:`, etc.)
- Take last non-empty line as defense against chain-of-thought

## Review Workflow

### `idiom-review` command

Queries all candidates with `candidate_status = 'translated'` and writes a JSON review file to `artifacts/releases/<release>/idioms/review.json` plus a spreadsheet file to `artifacts/releases/<release>/idioms/review.csv`:

```json
{
  "review_schema_version": 1,
  "release_id": "...",
  "entries": [
    {
      "candidate_id": "ican_...",
      "source_text": "孤苦伶仃",
      "meaning_zh": "孤单困苦，无依无靠",
      "meaning_en": "lonely, destitute, and without support",
      "rendering": "lonely and destitute",
      "action": "keep"
    }
  ]
}
```

Supported user actions:
- `"keep"` — promote as-is (or with edited `rendering`)
- `"delete"` — skip this candidate
- `"add"` — new entry (no `candidate_id`, requires `source_text` + `rendering`)

`review.csv` uses fixed columns:

```
action	source_text	meaning_zh	meaning_en	rendering	candidate_id	evidence_snippet	alternatives
```

Production gates also generate `review.json` and `review.csv` automatically when unresolved idiom rendering votes block a downstream stage. The files remain human-editable inputs; promotion still requires an explicit `idiom-promote --review-file` run.

The command emits `preprocess-idioms.review.started`, one `review.*.artifact_written` event for each generated review file, and `preprocess-idioms.review.completed`. Unexpected generation errors emit `preprocess-idioms.review.failed` with `severity = "error"`, `phase`, and `error`.

### `idiom-promote --review-file`

If `--review-file` is provided, the command applies user edits from either `review.json` or `review.csv`, then runs standard validation + promotion.

Promotion emits `preprocess-idioms.promote.started`, artifact events for candidate, policy, and conflict snapshots, and `preprocess-idioms.promote.completed` with promotion/conflict counts. Unexpected promotion errors emit `preprocess-idioms.promote.failed` with `severity = "error"`, `phase`, and `error`.

## Cross-Chapter Deduplication

`idiom_candidates` has `UNIQUE (release_id, normalized_source_text)`. The upsert uses `ON CONFLICT(release_id, normalized_source_text)` with merge logic:

- `appearance_count` = existing + new
- `first_seen_chapter` = MIN of both
- `last_seen_chapter` = MAX of both
- `source_text` = latest detection
- `meaning_zh` = keep existing if non-empty

This prevents duplicate rows when the same idiom is detected across multiple chapters.

## Validation Ownership

- duplicate detection based on normalized source text
- category and policy status validation
- chapter-safe first_seen attribution

## Resume And Rerun

- idioms are additive; new chapters can be processed without clearing existing idioms
- re-running a chapter updates appearance counts and chapter range metadata
- default reruns use the durable phase checkpoint: `detect_completed`, `translated`, then `promoted`
- translate reruns skip already translated candidates and continue pending candidates
- promotion reruns process only unpromoted translated candidates by default
- `run retry-failed --stage preprocess-idioms` retries incomplete translation or promotion state without forcing approved policies. Idiom conflicts are reported as review-required and are not retried automatically.
- `--force` reruns detect, translate, and promote for the requested scope

## Tests

- idiom extraction from sample text
- duplicate detection and normalization
- exact-match retrieval for paragraph bundles
- storage and retrieval from SQLite repository
