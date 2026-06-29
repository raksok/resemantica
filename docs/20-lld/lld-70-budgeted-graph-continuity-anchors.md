# LLD 70: Budgeted Graph Continuity Anchors

## Summary

`preprocess-continuity` now renders a bounded, chapter-relevant graph anchor
view for `SUMMARY_GRAPH_CONTINUITY_UPDATE`. The full chapter-safe graph remains
part of the continuity source hash, but the analyst prompt receives only the
anchors most relevant to the current update.

This prevents late-story runs from failing prompt budget checks when the
chapter-safe graph has grown to thousands of entities and relationships.

## Behavior

For each chapter, continuity input construction builds two anchor views:

1. A full raw chapter-safe view used only for `source_hash`.
2. A bounded rendered view used in the analyst prompt and per-chapter artifact.

The bounded view prioritizes:

- entities with appearances in the current recent-summary window
- safe aliases for selected entities
- active safe relationships touching recent entities, ordered by local endpoint
  coverage, recency, confidence, and stable relationship id

If no recent entity appearances exist, the renderer falls back to the safe graph
order and still stops before the internal anchor token budget.

## Resume And Staleness

Completed chunk resume behavior is unchanged. Existing rows remain current when
their `derived_from_chapter_hash` matches the full raw continuity source hash,
the English row is current, and the artifact exists.

Because the full safe graph still drives `source_hash`, newly confirmed graph
state can stale continuity rows even when that state is not selected into the
bounded prompt view.

## Events And Artifacts

When bounded rendering drops raw safe graph rows, the stage emits:

- `preprocess-continuity.graph_anchors_pruned`

The graph continuity artifact stores the bounded prompt anchors and audit
metadata, including selected counts, raw counts, selected token count, raw token
count, and the internal anchor token budget.

## Failure Policy

Prompt budget preflight remains mandatory before the analyst LLM call. A prompt
budget failure after anchor pruning means the previous compact continuity,
recent summaries, fixed prompt text, or selected anchor budget still exceeds the
effective analyst context limit.

Invalid graph compact model output retry and cache validation behavior is
unchanged.
