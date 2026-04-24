# Task 14A: Fix Graph Pipeline Drift — LLM Extraction

- **Milestone:** M14A (inserted before M14B / former M14)
- **Depends on:** M13

## Goal

Bring the `preprocess-graph` stage into compliance with SPEC.md, ARCHITECT.md, and DATA_CONTRACT.md by replacing deterministic keyword-heuristic extraction with the `analyst_name` LLM for entity and relationship extraction, and adding all missing graph node/edge types.

## Drift Summary

### A. Graph Extractor is Deterministic, Not LLM-based

| Source | Spec Requirement | Current Implementation |
|--------|-----------------|----------------------|
| SPEC §5.2 | `analyst_name` used for entity extraction, relationship mining | `graph/extractor.py` — zero LLM calls; pure regex/keyword heuristics |
| SPEC §13.4 | "Raw model output may propose relationship edges" | No LLM proposes edges; hardcoded `_MEMBER_OF_HINTS`, `_LOCATED_IN_HINTS`, etc. |
| SPEC §12.1 | Graph used for "entity extraction support, alias linking, relationship mining" | Entities detected by glossary `source_text.count()`, aliases never extracted |
| ARCHITECT Hardware | analyst model = entity extraction | analyst model not invoked in graph pipeline |

### B. Missing Relationship Types (SPEC §12.3)

| Type | In `WORLD_MODEL_EDGE_TYPES`? | In `SUPPORTED_RELATIONSHIP_TYPES`? |
|------|---------------------------|-------------------------------|
| `ALIAS_OF` | ❌ | ❌ |
| `APPEARS_IN` | ❌ | ❌ |
| `MEMBER_OF` | ✅ | ✅ |
| `DISCIPLE_OF` | ❌ | ❌ |
| `MASTER_OF` | ❌ | ❌ |
| `ALLY_OF` / `ally_of` | ❌ | ✅ (lowercase, inconsistent) |
| `ENEMY_OF` | ❌ | ❌ |
| `LOCATED_IN` | ✅ | ✅ |
| `OWNS` | ❌ | ❌ |
| `USES_TECHNIQUE` | ❌ | ❌ |
| `PART_OF_ARC` | ❌ | ❌ |
| `NEXT_CHAPTER` | ❌ | ❌ |
| `HELD_BY` | ✅ | ✅ (not in SPEC) |
| `RANKED_AS` | ✅ | ✅ (not in SPEC) |
| `teacher_of` | ❌ | ✅ (lowercase, not in SPEC) |

### C. Missing Node Types (SPEC §12.2)

Chapter and Arc nodes are never created.

### D. Aliases Not Extracted

`provisional_aliases` is always empty. SPEC §12.1 requires alias linking. SPEC §5.2 says analyst model handles it.

## Scope

**In:**

1. Create `graph_extract.txt` prompt template for the analyst model
2. Refactor `graph/extractor.py` to call LLM per chapter for entity + relationship extraction
3. Add all missing edge types and normalize naming to uppercase convention in `graph/models.py`
4. Wire LLM client into `graph/pipeline.py`
5. Keep deterministic: ID hashing, deferred-entity registry, glossary linkage, validation, status promotion
6. Remove: keyword-heuristic constants, suffix-based category inference, hardcoded relationship hints

**Out:**

- Chapter/Arc node creation (separate concern for M7 world model)
- Embedding index for fuzzy support (separate concern)
- Changes to CLI, TUI, orchestration runner (no interface change needed)

## Owned Files or Modules

- `src/resemantica/graph/extractor.py` — **primary rewrite**
- `src/resemantica/graph/models.py` — add missing edge types
- `src/resemantica/graph/pipeline.py` — wire LLM client
- `src/resemantica/graph/validators.py` — verify after model changes
- `src/resemantica/llm/prompts/graph_extract.txt` — **new file**

- LLD: `../20-lld/lld-14a-graph-llm-drift.md`

## Interfaces to Satisfy

- `preprocess_graph()` signature unchanged (`graph/pipeline.py`)
- `extract_entities()` gains `llm_client` and `model_name` params
- Output still produces `GraphExtractionResult` with same field types
- All existing graph output artifacts (snapshot, warnings JSON) unchanged

## Tests or Smoke Checks

- `uv run python -m resemantica.cli preprocess graph --release test --chapters 1:3` completes without error
- Graph snapshot contains entities, appearances, and relationships with correct types
- All 12 SPEC edge types present in `SUPPORTED_RELATIONSHIP_TYPES`
- Deferred entities still created for CJK terms not in locked glossary
- Existing graph validation still passes

## Done Criteria

- `graph/extractor.py` calls `analyst_name` LLM for entity/relationship extraction, not keyword heuristics
- `graph/models.py` defines all 12 SPEC edge types with uppercase naming
- `graph/pipeline.py` builds and passes `LLMClient` to extractor
- `graph_extract.txt` prompt exists and produces parseable JSON output
- All pre-existing graph validation tests pass
- Batch pilot (M14B) can consume graph output without regressions
