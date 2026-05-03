# LLD 03: Canonical Glossary

## Summary

Build the glossary system as the first authority store after extraction. Discovery and candidate translation remain working state; explicit validation and promotion create locked glossary entries.

Post-MVP additions: deterministic candidate filtering, BGE-M3 embedding-based critic for semantic pruning, and a human-override review workflow.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli preprocess glossary-discover --release <release_id> [--pruning-threshold <float>]`
- `uv run python -m resemantica.cli preprocess glossary-translate --release <release_id>`
- `uv run python -m resemantica.cli preprocess glossary-promote --release <release_id> [--review-file <path>]`
- `uv run python -m resemantica.cli preprocess glossary-review --release <release_id>`

Python modules:

- `db.glossary_repo`
- `llm.client.translate_glossary_candidate()`
- `glossary.validators` — normalization, conflict detection, deterministic filtering
- `glossary.critic` — BGE-M3 embedding-based candidate pruning

SQLite datasets:

- `glossary_candidates` (includes `critic_score REAL` column)
- `locked_glossary`
- `glossary_conflicts`

## Data Flow

1. Read extracted chapter text.
2. Discover candidate terms with evidence and chapter ranges.
3. **Deterministic filter** — remove calendar dates, common non-setting terms via patterns and stop-list. Flagged entries get `candidate_status = "filtered"` and skip translation.
4. **BGE-M3 embedding critic** — score each remaining candidate by cosine similarity to a reference vocabulary of common Chinese words. Entries below `pruning_threshold` get `candidate_status = "pruned"` and skip translation. Score stored in `critic_score`.
5. Persist remaining candidates to working state.
6. Translate candidates to provisional English renderings.
7. **Optional human review** — `glossary-review` writes translated candidates to a JSON review file. User edits translations, marks entries for deletion, or adds new entries. `glossary-promote --review-file` reads the edited file.
8. Run deterministic normalization and conflict checks.
9. Promote approved entries into locked glossary.

## Candidate Status Lifecycle

```
discovered → filtered     (deterministic filter — date/stop-list match)
          → pruned        (BGE-M3 critic — score below threshold)
          → translated    (survived all filters, LLM translation succeeded)
          → conflict      (failed deterministic validation during promotion)
          → promoted      (locked glossary)
```

## Required Fields

Candidate:

- `candidate_id`
- `source_term`
- `category`
- `first_seen_chapter`
- `last_seen_chapter`
- `appearance_count`
- `evidence_snippet`
- `candidate_translation_en`
- `validation_status`
- `critic_score` (nullable REAL — BGE-M3 similarity score, lower means more like common vocab)

Locked glossary entry:

- `glossary_entry_id`
- `source_term`
- `target_term`
- `category`
- `approved_at`
- `approval_run_id`
- `schema_version`

## Deterministic Filter (`glossary/validators.py`)

**Date/time pattern filter** — regex targeting Chinese date expressions:
- `X月X日`, `X月X号`, `X年X月X日`, `X月初X`, `X月中旬`
- Both numeric (`3月5日`) and CJK (`三月初三`, `二零二五年`) forms
- Near-zero false positive risk — only matches explicit date patterns

**Stop-list filter** — exact-match against a curated set of ~30 common Chinese nouns and expressions that are frequent LLM false positives:
- Generic nouns: `乡塾`, `学校`, `时候`, `时间`, `地方`, `家里`, `面前`, `身后`
- Temporal/discourse: `这时`, `那时`, `突然`, `虽然`, `但是`, `因为`, `所以`

## BGE-M3 Embedding Critic (`glossary/critic.py`)

### Scoring Method

A nearest-neighbor classifier in embedding space:

1. **Reference vocabulary**: A built-in list of ~100 common Chinese words that should never be glossary terms (dates, common nouns, function words, numerals). Packaged as a Python constant in `critic.py`.

2. **At startup**: Load `BAAI/bge-m3` via `sentence-transformers` (CPU, ~560MB RAM). Embed the reference vocabulary once, normalize to unit vectors.

3. **Per-candidate scoring**:
   ```
   embedding = model.encode(f"{source_term} [{category}]", normalize_embeddings=True)
   max_similarity = max(dot_product(embedding, ref) for ref in reference_embeddings)
   critic_score = 1.0 - max_similarity
   ```
   Score of 1.0 = maximally unlike any common word (likely glossary-worthy).
   Score of 0.0 = identical to a common word (definitely not glossary-worthy).

4. **Pruning**: If `critic_score < pruning_threshold`, set `candidate_status = "pruned"` and store score. Candidate skips translation.

### Configuration

- `models.embedding_name` — HuggingFace model ID (default: `BAAI/bge-m3`)
- `models.pruning_threshold` — float in [0, 1] (default: `0.3`). Set to `0` for evaluation-only mode (score without pruning).

### Evaluation Workflow

1. Run `glossary-discover --pruning-threshold 0` on a full release
2. BGE-M3 scores every candidate but prunes nothing
3. Scores stored in `glossary_candidates.critic_score`
4. After manual review, export labeled data and find optimal threshold via precision/recall

## Translation Prompt (`llm/prompts/glossary_translate.txt`)

```
# version: 2.0

CONTEXT: {EVIDENCE_SNIPPET}

This is text of {CATEGORY}, Translate the following `zh` into `en` with no extra explanation.

{SOURCE_TERM}
```

Response post-processing strips label prefixes (`Category:`, `Translation:`, etc.) and takes only the last non-empty line as defense against chain-of-thought leakage.

## Review Workflow

### `glossary-review` command

Queries all candidates with `candidate_status = 'translated'` and writes a JSON review file to `artifacts/releases/<release>/glossary/review.json`:

```json
{
  "review_schema_version": 1,
  "release_id": "test-1",
  "generated_at": "2026-05-03T12:00:00Z",
  "entries": [
    {
      "candidate_id": "gcan_abc123",
      "source_term": "稚圭",
      "category": "character",
      "translation": "Zhi Gui",
      "evidence_snippet": "...",
      "action": "keep"
    }
  ]
}
```

Supported user actions:
- `"keep"` — promote as-is (or with edited `translation`)
- `"delete"` — skip this candidate
- `"add"` — new entry (no `candidate_id`, requires `source_term` + `category` + `translation`)

### `glossary-promote --review-file`

If `--review-file` is provided, the command:
1. Reads the file and validates `review_schema_version`
2. Applies translation overrides for `keep` entries
3. Skips `delete` entries
4. Inserts `add` entries as new candidates
5. Runs existing deterministic validation + promotion unchanged

Without `--review-file`, behavior is identical to the original MVP flow.

## Validation Ownership

- normalization, duplicate detection, and policy checks are deterministic code
- promotion must be transactional
- candidate history remains intact after promotion

## Resume And Rerun

- repeated discovery for the same source hash must be idempotent
- promotion never mutates historical candidate evidence
- glossary-dependent downstream artifacts are invalidated by locked glossary hash changes

## Tests

- discovery writes candidates only
- promotion writes locked glossary only after validation
- duplicate detection and conflict recording
- exact glossary match precedence over future fuzzy sources
- deterministic filter catches date patterns and stop-list terms
- BGE-M3 critic stores scores without blocking at threshold=0

## Out Of Scope

- summary generation
- graph alias resolution
- fuzzy retrieval implementation
