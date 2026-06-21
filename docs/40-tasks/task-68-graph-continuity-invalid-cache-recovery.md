# Task 68: Graph Continuity Invalid Cache Recovery

## Milestone

M68

## Depends On

M67

## Goal

Prevent invalid graph continuity LLM cache entries from causing repeat
`preprocess-continuity` failures.

## Scope

- Validate `SUMMARY_GRAPH_CONTINUITY_UPDATE` output before accepting cached text.
- Treat invalid cached graph continuity output as stale and regenerate once.
- Cache only validated fresh graph continuity output.
- Report clear errors for empty and malformed fresh model output.
- Document recovery behavior for stale empty or malformed cache entries.

## Owned Files Or Modules

- `src/resemantica/summaries/continuity.py`
- `tests/summaries/test_graph_continuity_refresh.py`
- Graph continuity LLD, task README, and troubleshooting documentation

## Interfaces

No CLI flag, prompt schema, database schema, artifact shape, graph state, or
packet interface changes.

## Tests

- Seed an empty graph continuity cache output, rerun, and assert regeneration
  overwrites it with valid output.
- Assert fresh empty graph continuity model output raises
  `graph_continuity_output_invalid: empty model output` without writing cache.
- Seed malformed cached JSON and assert it is treated as stale and regenerated
  once.
- Keep existing graph continuity persistence, graph anchor, budget, and
  missing-snapshot tests passing.

## Done Criteria

- Invalid cached graph continuity output no longer creates sticky repeat
  failures.
- Fresh invalid graph continuity output fails clearly and does not poison cache.
- Targeted graph continuity, summary pipeline, retry-failed orchestration, and
  Ruff checks pass.
