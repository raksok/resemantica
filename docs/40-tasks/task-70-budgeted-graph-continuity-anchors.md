# Task 70: Budgeted Graph Continuity Anchors

## Milestone

M70

## Depends On

M69

## Goal

Prevent late-story `preprocess-continuity` prompt budget failures caused by
rendering the full chapter-safe graph into each graph continuity prompt.

## Scope

- Render bounded, chapter-relevant graph anchors for analyst prompts and
  graph-continuity artifacts.
- Keep full raw chapter-safe anchors in the continuity source hash so resume and
  staleness remain conservative.
- Prefer current/recent chapter entities and active relationships before older
  or unrelated safe graph rows.
- Emit pruning audit telemetry when bounded rendering drops raw safe graph rows.
- Keep CLI, TOML config, invalid-output retry, chunk resume, and cleanup scope
  unchanged.

## Owned Files Or Modules

- `src/resemantica/summaries/continuity.py`
- `tests/summaries/test_graph_continuity_refresh.py`
- Continuity LLD/task/manual documentation

## Interfaces

Python:

- `build_graph_continuity_anchors(..., recent_summary_chapters: list[int] | None = None, max_anchor_tokens: int | None = None)`

Default direct-call behavior remains the full chapter-safe anchor view.

Events:

- `preprocess-continuity.graph_anchors_pruned`

## Tests

- Large unrelated graph anchors are pruned below prompt budget and the analyst
  LLM is still called.
- Current/recent entities and relationships are retained before older/global
  anchors.
- Bounded anchors continue excluding future aliases and relationships.
- Source hash changes when the full raw safe anchor set changes, even when the
  bounded prompt subset is unchanged.
- Pruning events and artifact audit metadata include raw and selected counts.
- Existing invalid-cache, fresh invalid-output retry, and chunk resume tests
  remain passing.

## Done Criteria

- Late-story graph continuity prompts stay under the effective analyst prompt
  budget when the full chapter-safe graph is large.
- Completed chunk resume remains compatible with existing row source hashes.
- Targeted tests and Ruff checks pass.
