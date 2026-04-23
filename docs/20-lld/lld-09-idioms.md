# LLD 09: Idioms Workflow

## Summary

Detect idioms and set phrases, capture their meaning and preferred English rendering, and store them as authoritative structured assets for packet assembly and translation support.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli preprocess idioms --release <release_id>`

Python modules:

- `idioms.extractor.extract_idioms()`
- `idioms.matching.match_idioms()`
- `idioms.validators.validate_idiom_policy()`
- `idioms.repo.IdiomRepository`

SQLite datasets:

- `idioms` (source_text, meaning_zh, preferred_rendering_en, status, etc.)

## Data Flow

1. Read extracted chapter text.
2. Use `analyst_name` model to detect candidate idioms and set phrases.
3. Capture Chinese meaning and propose English rendering policy.
4. Perform deterministic normalization and duplicate detection.
5. Promote validated idioms into the authoritative idiom store.
6. Provide exact-match lookup for packet assembly.

## Validation Ownership

- duplicate detection based on normalized source text
- category and policy status validation
- chapter-safe first_seen attribution

## Resume And Rerun

- idioms are additive; new chapters can be processed without clearing existing idioms
- re-running a chapter updates appearance counts and chapter range metadata

## Tests

- idiom extraction from sample text
- duplicate detection and normalization
- exact-match retrieval for paragraph bundles
- storage and retrieval from SQLite repository
