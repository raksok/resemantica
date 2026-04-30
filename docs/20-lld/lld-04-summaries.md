# LLD 04: Summary Memory

## Summary

Create authoritative Chinese continuity memory and derived English summaries. Chinese summaries are validated continuity truth. English summaries exist for operator inspection and packet assembly support only.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli preprocess summaries --release <release_id>`

Python modules:

- `summaries.generator.generate_chapter_summary()`
- `summaries.validators.validate_chinese_summary()`
- `summaries.derivation.build_story_so_far()`
- `summaries.derivation.derive_english_summary()`

SQLite datasets:

- `summary_drafts`
- `validated_summaries_zh`
- `derived_summaries_en`

Structured Chinese summary schema:

```json
{
  "chapter_number": 3,
  "is_story_chapter": true,
  "characters_mentioned": ["张三", "李四"],
  "key_events": ["张三加入青云门", "李四获得秘籍"],
  "new_terms": ["青云门", "玄天秘籍"],
  "relationships_changed": [
    {"entity": "张三", "change": "became disciple of 青云门"}
  ],
  "setting": "青云山",
  "tone": "tense",
  "narrative_progression": "张三踏上修仙之路，遭遇初次考验"
}
```

`is_story_chapter` is mandatory (LLD 18b). When `false`, no row is written to `validated_summaries_zh`.

## Data Flow

1. Read extracted chapter content and locked glossary.
2. Generate `chapter_summary_zh_structured` JSON drafts.
3. Validate terminology, chronology, and future-knowledge safety.
4. Derive `chapter_summary_zh_short` from the structured summary's `narrative_progression` field.
5. **Materialize both `chapter_summary_zh_structured` and `chapter_summary_zh_short` as dedicated rows** in `validated_summaries_zh` with distinct `summary_type` values. The `content_zh` column for `zh_short` holds the `narrative_progression` string. This materialization occurs inside `summaries.generator.generate_chapter_summary()` as a single-transaction write — both rows are written atomically. No separate materialization stage or lazy extraction exists. The `summary_repo.save()` method accepts the structured JSON response and writes both rows; it does not store raw JSON for later splitting. This is mandatory so that Phase 1 (translation) and Phase 1.5 (packet assembly) perform zero JSON parsing to obtain continuity text.
6. Persist validated Chinese summaries.
6. Derive `story_so_far_zh` from prior validated state plus current validated chapter summary.
7. Derive English summaries from validated Chinese summaries plus locked glossary.

## Validation Ownership

- only validated Chinese summaries may feed continuity state
- `chapter_summary_zh_structured` must validate as JSON with all required fields
- `chapter_summary_zh_short` must be derived from `narrative_progression`, not independently invented
- both `zh_structured` and `zh_short` must be materialized as separate rows in `validated_summaries_zh` inside `generate_chapter_summary()` before any downstream consumer reads them; lazy extraction by consumers is forbidden
- English summaries must record provenance hashes back to validated Chinese inputs
- summary validation must fail on future-knowledge leakage

## Resume And Rerun

- any change to locked glossary or validated Chinese summary invalidates dependent English summaries and packet inputs
- `story_so_far_zh` is rebuilt deterministically from validated predecessors, never from English output

## Tests

- future-knowledge leak detection
- glossary conflict detection in Chinese summary validation
- English summaries remain derived and separate from authority state
- structured JSON schema validation and short-summary derivation
- deterministic rebuild of `story_so_far_zh`

## Out Of Scope

- packet assembly
- arc graph integration beyond placeholder hooks
