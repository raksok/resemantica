# LLD 03: Canonical Glossary

## Summary

Build the glossary system as the first authority store after extraction. Discovery and candidate translation remain working state; explicit validation and promotion create locked glossary entries.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli preprocess glossary-discover --release <release_id>`
- `uv run python -m resemantica.cli preprocess glossary-translate --release <release_id>`
- `uv run python -m resemantica.cli preprocess glossary-promote --release <release_id>`

Python modules:

- `db.glossary_repo`
- `llm.client.translate_glossary_candidate()`
- `glossary.validators.validate_candidate()` if a dedicated package is later introduced

SQLite datasets:

- `glossary_candidates`
- `locked_glossary`
- `glossary_conflicts`

## Data Flow

1. Read extracted chapter text.
2. Discover candidate terms with evidence and chapter ranges.
3. Persist candidates to working state only.
4. Translate candidates to provisional English renderings.
5. Run deterministic normalization and conflict checks.
6. Promote approved entries into locked glossary.

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

Locked glossary entry:

- `glossary_id`
- `source_term`
- `target_term`
- `category`
- `approved_at`
- `approval_run_id`
- `schema_version`

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

## Out Of Scope

- summary generation
- graph alias resolution
- fuzzy retrieval implementation
