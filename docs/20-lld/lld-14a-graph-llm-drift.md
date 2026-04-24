# LLD 14A: Graph Pipeline Drift Fix — LLM Extraction

## Summary

Replace deterministic keyword-heuristic extraction in `graph/extractor.py` with analyst-model LLM prompts while preserving deterministic ID generation, deferred-entity logic, validation, and status promotion. Add all missing SPEC-defined edge types to the graph model.

## Current State

`graph/extractor.py` uses:
- Regex pattern matching (`_CJK_TERM_RE`, `_SENTENCE_SPLIT_RE`)
- Suffix guessing for category inference (`_FACTION_SUFFIXES`, `_LOCATION_SUFFIXES`)
- Hardcoded keyword tuples for relationship hints (`_MEMBER_OF_HINTS`, `_LOCATED_IN_HINTS`, etc.)
- Zero LLM calls

Only 4 world-model edge types are extracted: `MEMBER_OF`, `LOCATED_IN`, `HELD_BY`, `RANKED_AS`.

## Target State

1. Analyst LLM extracts entities per chapter with category, aliases, and evidence
2. Analyst LLM proposes relationships with type, source/target, confidence, and chapter-safe metadata
3. All 12 SPEC §12.3 edge types accessible: `ALIAS_OF`, `APPEARS_IN`, `MEMBER_OF`, `DISCIPLE_OF`, `MASTER_OF`, `ALLY_OF`, `ENEMY_OF`, `LOCATED_IN`, `OWNS`, `USES_TECHNIQUE`, `PART_OF_ARC`, `NEXT_CHAPTER`
4. Edge type naming normalized to uppercase convention
5. Deterministic code preserved for: ID hashing, deferred-entity registry, glossary linkage, validation, `provisional→confirmed` promotion

## Prompt Contract

**File:** `src/resemantica/llm/prompts/graph_extract.txt`

The prompt must instruct the analyst model to return JSON with:

- `entities`: array of `{source_term, entity_type, aliases: [text], evidence_snippet}`
- `relationships`: array of `{type, source_term, target_term, evidence_snippet, confidence, lore_text?, is_masked_identity?}`

Entity types: `character, alias, title_honorific, faction, location, technique, item_artifact, realm_concept, creature_race, generic_role, event`

Relationship types: all 12 SPEC edge types

## Public Interfaces

### Unchanged

- `preprocess_graph(release_id, run_id, config, project_root, graph_client, chapter_start, chapter_end)` — signature identical
- `GraphExtractionResult` — same field types
- Graph snapshot JSON artifact — same schema
- Graph warnings JSON artifact — same schema

### Changed

- `extract_entities()` gains `llm_client: LLMClient` and `model_name: str` parameters
- `graph/models.py` — `SUPPORTED_RELATIONSHIP_TYPES` expanded to all 12 SPEC types
- `graph/models.py` — `WORLD_MODEL_EDGE_TYPES` expanded to include all new types
- New prompt file: `llm/prompts/graph_extract.txt`

## Data Flow

```
glossary pipeline
  → locked glossary entries
  → preprocess_graph()
     → build LLMClient from config.models.analyst_name
     → extract_entities(llm_client, model_name, ...)
        → per extracted chapter JSON:
           → load prompt template
           → render with source_text_zh + chapter_number + glossary subset
           → call llm_client.generate_text(model=analyst_name)
           → parse JSON response
           → create GraphEntity, GraphAppearance, GraphAlias, GraphRelationship
           → all marked status="provisional"
        → CJK terms not in locked glossary → deferred entities (deterministic)
     → upsert deferred entities to SQLite (deterministic)
     → resolve deferred → promoted glossary-matched entities (deterministic)
     → validate_graph_state() (deterministic)
     → promote provisional→confirmed (deterministic)
     → upsert to LadybugDB (deterministic)
     → save snapshot
```

## Validation

- All 12 relationship types present in `SUPPORTED_RELATIONSHIP_TYPES` enum
- JSON output from LLM parses without error for each chapter
- Chapter-safe field validation passes (start_chapter ≤ N, end_chapter ≥ N, revealed_chapter ≤ N)
- Deferred entity registry still populated correctly
- Existing graph snapshot + warnings artifact structure unchanged

## Files Changed

| File | Change |
|------|--------|
| `src/resemantica/llm/prompts/graph_extract.txt` | New — analyst prompt for entity/relationship extraction |
| `src/resemantica/graph/extractor.py` | Rewrite extraction to call LLM; remove keyword heuristics |
| `src/resemantica/graph/models.py` | Add missing edge types; normalize naming |
| `src/resemantica/graph/pipeline.py` | Build and pass `LLMClient` to extractor |
| `src/resemantica/graph/validators.py` | Verify after model changes (likely no change needed) |
