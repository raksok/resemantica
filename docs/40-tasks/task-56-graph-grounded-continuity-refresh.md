# Task 56: Graph-Grounded Continuity Refresh

## Milestone

M56

## Depends On

M55, M6, M8, M15

## Goal

Add a post-graph continuity refresh stage so long-run compact continuity can be corrected from confirmed, chapter-safe graph state without replacing chapter-local summary generation or duplicating the graph.

## Scope

- Add `preprocess-continuity` between `preprocess-graph` and `packets-build`.
- Persist `story_so_far_zh_graph_compact` in `validated_summaries_zh`.
- Persist `story_so_far_en_graph_compact` in `derived_summaries_en`.
- Build deterministic graph anchors from confirmed chapter-safe entities, aliases, appearances, relationships, and revealed lore.
- Prefer graph-grounded compact continuity in packet assembly, falling back to existing compact and full story rows.
- Include the chosen graph-grounded row in packet summary provenance hashing.

## Owned Files Or Modules

- `src/resemantica/summaries/continuity.py`
- `src/resemantica/llm/prompts/summary_graph_continuity_update.txt`
- `src/resemantica/orchestration/`
- `src/resemantica/packets/builder.py`
- `src/resemantica/settings.py`

## Interfaces To Satisfy

- CLI: `rsem preprocess continuity --release <id> --run <id>`
- Python: `resemantica.summaries.continuity.preprocess_continuity(...)`
- Config: `summaries.graph_continuity_rebase_interval`, default `50`
- Summary rows:
  - `validated_summaries_zh.summary_type = story_so_far_zh_graph_compact`
  - `derived_summaries_en.summary_type = story_so_far_en_graph_compact`

## Tests Or Smoke Checks

- Graph anchors exclude future aliases and relationships.
- Refreshed continuity is saved and can reflect required graph anchors.
- Rebase interval uses previous milestone compact plus recent summaries.
- Over-budget continuity output fails clearly.
- Missing graph snapshot fails the stage contract.
- Packets prefer graph compact continuity and invalidate when it changes.
- Orchestration and CLI know the new stage order and dispatch.

## Done Criteria

- Production order is `preprocess-summaries`, `preprocess-glossary`, `preprocess-idioms`, `preprocess-graph`, `preprocess-continuity`, `packets-build`, `translate-range`, `epub-rebuild`.
- Existing summary pipeline behavior remains intact.
- Packet fallback behavior remains compatible when graph-grounded continuity is absent.
