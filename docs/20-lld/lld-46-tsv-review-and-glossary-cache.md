# LLD 46: TSV Review + Glossary-Aware Translation Cache

## Summary

Two quality-of-life improvements to the glossary review and translation pipeline:

1. **TSV review file** — alongside the existing JSON review file, generate a tab-separated file that opens directly in Excel/Sheets for human editing.
2. **Glossary-aware translation cache** — include `packet_version_hash` in translation checkpoints so that upstream changes (glossary, summaries, graph, idioms) automatically invalidate the cache and trigger re-translation without needing `--force`.

## TSV Review Format

### Output

`glossary-review` writes `review.tsv` alongside `review.json` to the same directory (`{release_root}/glossary/`).

### Columns

| Column | Description | Editable |
|--------|-------------|----------|
| `action` | `keep`, `delete`, or blank (defaults to `keep`) | Yes |
| `source_term` | Chinese source term | No (informational, except for `add`) |
| `category` | Term category (faction, character, etc.) | No (informational, except for `add`) |
| `translation` | English rendering. Blank = keep current. | Yes |
| `candidate_id` | Internal ID. Blank for `add` entries. | No |
| `evidence_snippet` | Context excerpt, trunc to 120 chars, newlines→spaces | No |
| `alternatives` | Pipe-separated model votes | No |

### Rules

- First row is a header. Column order is fixed.
- Tab-separated. No quoting — tabs do not appear in Chinese source terms or English translations.
- `evidence_snippet`: internal newlines replaced with spaces, truncated to 120 characters.
- `alternatives`: pipe-separated `translation` values from model votes. Informational only — editing this column has no effect.
- UTF-8 encoding (with BOM handled on read for Excel compat).

### Input

`glossary-promote --review-file review.tsv` detects `.tsv` extension and parses accordingly. TSV rows desugar into the same internal `entries` list-of-dicts format consumed by `_apply_review_overrides()`.

## Pipeline Changes

### `review_glossary_candidates()`

After writing `review.json`, write `review.tsv`:

```
action\tsource_term\tcategory\ttranslation\tcandidate_id\tevidence_snippet\talternatives
keep\t青云门\tfaction\tAzure Sect\tgcan_abc123\t青云门弟子张三来到青云山\tAzure Sect|Blue Cloud Sect
keep\t苍云门\tfaction\t\tgcan_def456\t苍云门长老\tCangyun Gate|Azure Cloud Sect|Blue Cloud Gate
```

### `promote_glossary_candidates()`

Detect input format by file extension:
- `.json` → existing JSON parsing with schema version check
- `.tsv` → parse via `csv.reader(delimiter='\t')`, convert rows to `entries` dicts
- Other → raise `ValueError`

Helper `_read_review_file(path) -> list[dict]` handles TSV→entries conversion, including validation and error messages.

## Cache Invalidation Design

### Problem

Translation checkpoints are keyed on `(release_id, run_id, chapter_number, pass_name)` and validated against `source_hash` + `prompt_version`. When glossary terms change (or summaries, graph, idioms), the chapter source text doesn't change, so the cache incorrectly hits and skips re-translation.

### Solution

Store `packet_version_hash` alongside existing checkpoint fields.

### `packet_version_hash` definition

Reuse `PacketMetadataRecord.packet_hash` — a SHA-256 hash of all packet inputs (glossary + summaries + graph + idioms + builder version). This is already computed during packet build and stored in the `packet_metadata` table.

Using `packet_hash` instead of only `glossary_version_hash` future-proofs the cache: future upstream changes (summaries, graph, etc.) will also auto-invalidate.

### Schema

```sql
ALTER TABLE translation_checkpoints
ADD COLUMN packet_version_hash TEXT NOT NULL DEFAULT '';
```

### Checkpoint flow

```
translate_chapter_pass1(release_id, chapter_number, ...)
  │
  ├─ metadata = get_latest_packet_metadata(conn, release_id, chapter_number)
  │     └─ if None → packet_version_hash = ""
  │
  ├─ checkpoint = load_checkpoint(..., packet_version_hash=metadata.packet_hash)
  │     └─ query: ... AND packet_version_hash = ?
  │
  ├─ if checkpoint match → cache hit (skip)
  │
  └─ if no match → translate, save_checkpoint(..., packet_version_hash=metadata.packet_hash)
```

### Edge cases

| Case | Behavior |
|------|----------|
| No packet metadata exists | `packet_version_hash = ""` → won't match stored non-empty hash → cache miss |
| Old checkpoint rows without column | Schema migration sets default `""`. `load_checkpoint` queries for `""` but row has non-empty hash → no match → cache miss |
| Chapter with zero glossary terms | Packet still built with `packet_hash` → cache works |
| `run production` after glossary edit | Packet rebuilds → new hash → checkpoint miss → auto-re-translate |

## Files Touched

- `src/resemantica/glossary/pipeline.py` — TSV export + TSV import
- `src/resemantica/cli.py` — help text
- `src/resemantica/db/sqlite.py` — schema migration
- `src/resemantica/translation/checkpoints.py` — dataclass + query + write
- `src/resemantica/translation/pipeline.py` — pass1/pass2/pass3 integration
- `tests/glossary/test_glossary_pipeline.py` — TSV tests
- `tests/translation/test_translate_chapter.py` — cache invalidation tests
- `tests/translation/test_checkpoints.py` — checkpoint hash unit tests

## Testing

See task brief test checklist.
