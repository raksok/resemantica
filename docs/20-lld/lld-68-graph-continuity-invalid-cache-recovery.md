# LLD 68: Graph Continuity Invalid Cache Recovery

## Summary

`preprocess-continuity` validates graph continuity LLM output before accepting it
from cache or writing it to cache.

This prevents an empty or malformed `SUMMARY_GRAPH_CONTINUITY_UPDATE` response
from becoming a sticky failure. Existing invalid cache entries are treated as
stale and regenerated on the next run.

## Behavior

For each graph continuity refresh:

1. Render the graph continuity prompt and build the LLM cache identity.
2. If a cache entry exists, parse and validate its `raw_output`.
3. Accept the cached output only when it is valid JSON with non-empty
   `continuity_zh`, valid `anchor_audit`, and an in-budget compact text.
4. If cached output is invalid, ignore it and call the analyst model once.
5. Validate the fresh model output before saving it to cache.
6. Save only validated successful fresh output.

Invalid fresh output fails the chapter and does not write a cache entry.

## Failure Policy

- Empty model output fails with
  `graph_continuity_output_invalid: empty model output`.
- Malformed JSON or non-object JSON fails with
  `graph_continuity_output_invalid: expected JSON object`.
- Empty `continuity_zh`, over-budget `continuity_zh`, and invalid
  `anchor_audit` keep their existing validation failures.

## Scope

This change does not alter prompt schema, database schema, artifact shape,
graph state, packet selection, or chapter-level durable resume behavior.

## Tests

- Empty cached graph continuity output is regenerated and overwritten.
- Malformed cached graph continuity JSON is regenerated once.
- Fresh empty graph continuity output fails clearly without writing cache.
- Existing graph anchor, persistence, budget, and missing-snapshot checks remain.
