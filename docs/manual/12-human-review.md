# 12. Human Review Workflow

The human review workflow lets you inspect and correct glossary and idiom candidates before they are promoted to the locked stores. The cycle is:

```text
discover → translate → review → (edit) → promote
```

## Glossary Review

### Generate Review Files

```bash
uv run rsem preprocess glossary-review -r v1.0
```

Produces two files at `<release_root>/glossary/`:
- `review.json` — Full structured data with all fields
- `review.csv` — Tab-separated spreadsheet-friendly format

Review generation is database and file I/O only; it does not call translation or
analysis models. On large releases, glossary review uses indexed lookups over
translated candidates and translation votes instead of scanning every discovered
candidate.

If only the voter logic changed and existing model votes are still valid, re-run
the saved-vote resolver before regenerating review files:

```bash
uv run rsem preprocess glossary-resolve -r v1.0 -R glossary-translate
uv run rsem preprocess glossary-review -r v1.0
```

`glossary-resolve` does not call LLMs. It replays saved
`glossary_translation_votes`, updates canonical candidate translations, and then
`glossary-review` reflects the new resolved/unresolved state in `review.json`
and `review.csv`.

For releases with many unresolved vote disagreements, an optional filler pass can
ask one or more extra models only about the unresolved glossary candidates before
review generation:

```bash
uv run rsem preprocess glossary-resolve -r v1.0 -R glossary-translate
uv run rsem preprocess glossary-fill -r v1.0 -R glossary-translate --model <filler-model>
uv run rsem preprocess glossary-review -r v1.0
```

`glossary-fill` stores filler outputs as ordinary auditable
`glossary_translation_votes` rows and then reuses deterministic resolution with
the filler model names appended after the configured translator models. It does
not run full glossary translation and does not replace human review for policy
disagreements that remain unresolved.

For a stronger first-pass review, add `--pick-existing`:

```bash
uv run rsem preprocess glossary-fill -r v1.0 -R glossary-translate --model <filler-model> --pick-existing
```

Picker mode asks the model to choose one existing alternative only. Accepted
picks update the candidate translation and write an auditable `<model>:picker`
vote; original votes remain unchanged. Promotion still validates against locked
glossary entries, so picker mode does not overwrite already locked glossary
terms.

### Review File Format

**JSON structure:**
```json
{
    "review_schema_version": 1,
    "release_id": "v1.0",
    "instructions": "Edit 'translation' to override...",
    "entries": [
        {
            "candidate_id": "gcan_abc123",
            "source_term": "修仙",
            "category": "concept",
            "translation": "",
            "evidence_snippet": "...
修仙之路...",
            "alternatives": [
                {
                    "model_name": "HY-MT1.5-7B",
                    "translation": "cultivation",
                    "resolution_status": "pending"
                }
            ],
            "action": "keep"
        }
    ]
}
```

**CSV columns** (tab-separated):

| Column | Editable | Description |
|--------|----------|-------------|
| `action` | Yes | `keep`, `delete`, or `add` |
| `source_term` | Yes (for `add`) | Chinese term |
| `category` | Yes (for `add`) | Term category (person, place, concept, etc.) |
| `translation` | Yes | Override the English rendering |
| `candidate_id` | No (empty for `add`) | Internal ID |
| `evidence_snippet` | Yes (for `add`) | Context from source text |
| `alternatives` | No (informational) | Pipe-delimited model translations |

### Editing Instructions

For each entry you can:

- **`"action": "keep"`** (default) — Include in promotion. Optionally edit the `translation` field to override the English rendering.
- **`"action": "delete"`** — Exclude this candidate from promotion.
- **`"action": "add"`** — Insert a new entry. Omit `candidate_id`, provide `source_term`, `category`, `translation`, and optionally `evidence_snippet`.

### Promote with Edits

```bash
uv run rsem preprocess glossary-promote -r v1.0 -F artifacts/v1.0/glossary/review.csv
```

**How promotion consumes the review file:**

1. **Read** — Auto-detects format by extension (`.csv` or `.json`).
2. **Apply overrides** — `_apply_review_overrides()` processes each entry:
   - **Existing candidates** (by `candidate_id`):
     - `delete`: skipped from promotion.
     - Changed `translation`: updates the candidate's `candidate_translation_en`, resets `validation_status` to `'pending'`, clears `conflict_reason`.
   - **New entries** (`action: add`, no `candidate_id`):
     - Generates synthetic ID `gcan_review_<sha256_prefix>`.
     - Creates candidate with `discovery_run_id="review"`, `translator_model_name="human"`.
     - Upserts into `glossary_candidates` table.
3. **Validate** — `validate_candidates_for_promotion()` checks for conflicts against existing `locked_glossary` entries.
4. **Promote** — Conflict-free entries are promoted to `locked_glossary` and marked `candidate_status = 'promoted'`. Conflicts are written to `conflicts.json`.

## Idiom Review

### Generate Review Files

```bash
uv run rsem preprocess idiom-review -r v1.0
```

Produces `<release_root>/idioms/review.json` and `review.csv`.

### Review File Format

**JSON structure:**
```json
{
    "review_schema_version": 1,
    "release_id": "v1.0",
    "entries": [
        {
            "candidate_id": "ican_def456",
            "source_text": "对牛弹琴",
            "meaning_zh": "对不懂道理的人讲道理",
            "meaning_en": "",
            "rendering": "",
            "evidence_snippet": "...对牛弹琴...",
            "alternatives": [
                {
                    "model_name": "Qwen3.5-9B-GLM5.1",
                    "kind": "rendering",
                    "translation": "casting pearls before swine",
                    "resolution_status": "pending"
                }
            ],
            "action": "keep"
        }
    ]
}
```

**CSV columns** (tab-separated):

| Column | Editable | Description |
|--------|----------|-------------|
| `action` | Yes | `keep`, `delete`, or `add` |
| `source_text` | Yes (for `add`) | Chinese idiom text |
| `meaning_zh` | Yes (for `add`) | Chinese meaning explanation |
| `meaning_en` | Yes | English meaning explanation |
| `rendering` | Yes | Override the English idiom rendering |
| `candidate_id` | No (empty for `add`) | Internal ID |
| `evidence_snippet` | No | Context from source text |
| `alternatives` | No (informational) | Pipe-delimited `kind:translation` pairs |

Key difference from glossary review: idioms have **two vote kinds** — `'rendering'` (the English translation) and `'meaning'` (the semantic explanation). The CSV alternatives column encodes both with a `kind:` prefix.

### Editing Instructions

- **`"action": "keep"`** — Include in promotion. Edit `rendering` and/or `meaning_en`.
- **`"action": "delete"`** — Exclude from promotion.
- **`"action": "add"`** — Insert a new idiom. Provide `source_text`, `meaning_zh`, `rendering`, and optionally `meaning_en`, `usage_notes`, `evidence_snippet`.

### Promote with Edits

```bash
uv run rsem preprocess idiom-promote -r v1.0 -F artifacts/v1.0/idioms/review.csv
```

**How promotion consumes the review file:**

1. **Read** — Auto-detects format by extension.
2. **Apply overrides** — `_apply_idiom_review_overrides()`:
   - **Existing candidates** (`delete` or updated `rendering`/`meaning_en`).
   - **New entries**: synthetic ID `ican_review_<sha256_prefix>`, `detection_run_id="review"`, `translator_model_name="human"`, `analyst_model_name="human"`.
3. **Validate** — `validate_idiom_policy()` checks for conflicts against existing `idiom_policies`.
4. **Promote** — Conflict-free entries written to `idiom_policies`, candidates marked `candidate_status = 'approved'`.

## Without Review Files

If you skip the review step and call `glossary-promote` or `idiom-promote` without `--review-file`, the system promotes all candidates with:

- **Glossary**: `candidate_translation_en IS NOT NULL AND candidate_status != 'promoted' AND llm_keep = 1`
- **Idioms**: `candidate_status = 'translated'`

## Workflow Example

```bash
uv run rsem preprocess glossary-discover -r v1.0
```
```bash
uv run rsem preprocess glossary-translate -r v1.0
```
```bash
uv run rsem preprocess glossary-review -r v1.0
```
```bash
uv run rsem preprocess glossary-promote -r v1.0 -F artifacts/v1.0/glossary/review.csv
```
```bash
cat artifacts/v1.0/glossary/conflicts.json
```
