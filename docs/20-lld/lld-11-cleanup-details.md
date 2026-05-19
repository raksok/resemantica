# LLD 11: Detailed Cleanup Workflow

## Summary

Implement the explicit, scoped, and previewable cleanup/reset workflow to allow safe project restarts and artifact management.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli run cleanup-plan --scope <run|translation|preprocess|cache|keep-extracted|last-good-chunk|all|factory> [--run-id <id>]`
- `uv run python -m resemantica.cli run cleanup-apply --scope <run|translation|preprocess|cache|keep-extracted|last-good-chunk|all|factory> [--run-id <id>]`

Python modules:

- `orchestration.cleanup.plan_cleanup()`
- `orchestration.cleanup.apply_cleanup()`

Artifacts:

- cleanup plan (JSON)
- cleanup report (JSON)

## Data Flow

1. Resolve requested scope and run/release context.
2. Identify deletable artifacts:
    - `run`: selected run directory.
    - `translation`: selected run's `translation/` directory.
    - `preprocess`: release-level `extracted/`, `summaries/`, `glossary/`, `idioms/`, `graph/`, and `packets/`.
    - `cache`: release-level `.cache/`.
    - `keep-extracted`: downstream artifacts and selected run translation output while preserving `extracted/`.
    - `last-good-chunk`: artifacts and rows after the last completed chunk for the failed/current stage.
    - `all`: everything under the release root except release-local stores and cleanup files.
    - `factory`: all release directories plus legacy global stores under artifact root.
3. Generate a "Cleanup Plan" listing all targets for deletion and all preserved assets.
4. If `--dry-run` is not set, execute deletions and row removals.
5. Record the final Cleanup Report.

## Scope Contract

Cleanup scopes are defined once in `orchestration.cleanup.CLEANUP_SCOPES` and reused by CLI and TUI.

| Scope | Filesystem deletion | SQLite deletion |
|---|---|---|
| `run` | `runs/<run_id>/` | tracking `events`/`run_state`, translation checkpoints, extraction metadata, preprocessing checkpoints/drafts/votes, graph drafts, packet metadata, generic run/checkpoint rows |
| `translation` | `runs/<run_id>/translation/` | translation checkpoints only |
| `preprocess` | `extracted/`, `summaries/`, `glossary/`, `idioms/`, `graph/`, `packets/` | extraction metadata plus preprocessing checkpoints/drafts/votes, graph drafts, packet metadata, generic run/checkpoint rows |
| `cache` | `.cache/` | none |
| `keep-extracted` | `summaries/`, `glossary/`, `idioms/`, `graph/`, `packets/`, `.cache/`, selected run `translation/` | tracking rows, translation checkpoints, downstream preprocessing checkpoints/drafts/votes, graph drafts, packet metadata, generic run/checkpoint rows; preserves `extracted_chapters` and `extracted_blocks` |
| `last-good-chunk` | summary or translation artifacts after the last completed chunk | stage-specific rows after the chunk boundary; summary checkpoints or translation run-state lists are rewound to `last_good_chapter` |
| `all` | all direct release-root children except protected stores and cleanup files | same run-scoped rows as `run` |
| `factory` | artifact-root `releases/`, legacy global `resemantica.db`, legacy global `graph.ladybug` | none |

Protected release-local files are `tracking.db`, `resemantica.db`, `graph.ladybug`, `cleanup_plan.json`, and `cleanup_report.json`.

## Validation Ownership

- cleanup MUST NOT delete source EPUBs or configuration files by default
- cleanup MUST NOT delete authoritative `locked_glossary` unless scope is `all`
- plans must be generated and persisted before execution
- apply validates plan schema, release/run identity, scope, expected root, and target containment
- `--force` may bypass scope mismatch only; it must not bypass release/run mismatch or path safety
- `last-good-chunk` resolves the stage from run state, or accepts `--stage preprocess-summaries|translate-range`; other stages are rejected

## Resume And Rerun

- cleanup operations are themselves recorded in the event stream and SQLite bookkeeping

## Tests

- dry-run preview accuracy
- scope isolation (e.g., clearing one run doesn't affect another)
- preservation of inputs and config
- release-aware artifact deletion
