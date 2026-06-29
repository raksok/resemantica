# LLD 56: Graph-Grounded Continuity Refresh

## Summary

`preprocess-continuity` runs after `preprocess-graph` and before packet build. It refreshes bounded Chinese story continuity from previous graph-grounded continuity, recent validated chapter summaries, and confirmed chapter-safe graph anchors.

The stage does not replace `preprocess-summaries`. Chapter-local summaries, full story-so-far, and initial compact continuity remain owned by the summary pipeline. The refresh stage closes long-run drift after graph validation has produced confirmed state.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli preprocess continuity --release <release_id> --run <run_id>`

Python:

- `summaries.continuity.preprocess_continuity(...)`
- `summaries.continuity.build_graph_continuity_anchors(...)`

Prompt:

- `summary_graph_continuity_update.txt`, version `1.0`

Config:

```toml
[summaries]
graph_continuity_rebase_interval = 50
```

## Data Flow

1. Require a graph snapshot row from `preprocess-graph`.
2. For each story chapter with `chapter_summary_zh_short`, read confirmed chapter-safe graph state through `GraphClient.get_chapter_safe_subgraph()`.
3. Build deterministic full raw anchors for source hashing:
   - entities whose `revealed_chapter <= chapter`
   - aliases whose reveal and first-seen chapters are safe
   - appearances at or before the chapter
   - relationships whose endpoints and reveal/start/end intervals are safe
   - revealed lore only when attached to visible relationships
4. Render a bounded prompt anchor view from the raw safe graph. The bounded view
   prefers entities appearing in the current recent-summary window and active
   relationships touching those entities before older or unrelated safe graph
   rows.
5. Render `summary_graph_continuity_update.txt` with:
   - previous graph compact continuity
   - recent chapter summaries
   - current chapter number
   - bounded graph anchors
6. Accept graph continuity LLM cache output only after parsing and validation.
   Invalid cached output is treated as stale and regenerated.
7. Validate fresh model output before writing it to the LLM cache. Fresh invalid
   graph compact output receives a small validation retry budget and is never
   cached unless a retry returns valid output.
8. Save Chinese output as `story_so_far_zh_graph_compact`.
9. In chunked batch-order runs, complete all Chinese graph compact rows for the chunk in chapter order before deriving English rows for that chunk.
10. Derive English inspection text as `story_so_far_en_graph_compact` using source-local locked glossary context for the generated Chinese compact text.
11. Write a per-chapter graph continuity artifact containing the summary row and bounded anchor audit metadata.

## Rebase Behavior

Normal chapters update from the previous graph compact row plus the last three chapter summaries and current graph anchors.

Every `summaries.graph_continuity_rebase_interval` chapters, the stage rebases from the previous milestone compact row and all chapter summaries since that milestone. This keeps drift bounded without rebuilding the graph or replaying the full story from chapter one on every refresh.

The continuity source hash remains based on the full raw chapter-safe graph
anchor set, not only the bounded prompt anchor view. This preserves conservative
staleness detection and keeps completed chunk resume compatible with existing
rows when the raw source has not changed.

## Packet Interaction

Packets select continuity in this order:

1. `story_so_far_zh_graph_compact`
2. `story_so_far_zh_compact`
3. `story_so_far_zh`

The selected summary row participates in `summary_version_hash`, so packet metadata becomes stale when refreshed continuity changes.

## Failure Policy

- Missing graph snapshot fails `preprocess-continuity`.
- Missing chapter short summary skips that chapter.
- Empty or non-JSON fresh model output is retried within the chapter and is not
  cached unless a retry succeeds.
- Empty or non-JSON cached graph continuity output is ignored as stale and regenerated.
- Output exceeding `summaries.story_compact_max_tokens` fails clearly.
- Large chapter-safe graphs are pruned into bounded prompt anchors before the
  analyst prompt budget check. Pruning emits
  `preprocess-continuity.graph_anchors_pruned` with raw and selected counts.
- `SUMMARY_EN_DERIVE` prompt budget overflow fails before the translator LLM call.
- Chunked resume skips a completed continuity chunk only when the checkpoint range matches, its `last_good_chapter` covers the chunk, expected rows are current, and expected artifacts exist.
- In incomplete chunked resumes, current approved Chinese graph compact rows may be reused by source hash, and missing or stale English graph compact rows are backfilled without analyst calls.
- `run retry-failed --stage preprocess-continuity` plans from failed chunk
  checkpoint boundaries and also treats missing English graph compact rows or
  missing graph continuity artifacts as retryable continuity work.

## Tests

- graph anchor future-state exclusion
- refreshed row persistence and English derivation
- rebase interval source selection
- token budget failure
- invalid graph continuity cache recovery
- fresh invalid graph continuity output retry
- missing snapshot failure
- packet preference and invalidation
- prompt JSON-only and anti-restart regression checks
