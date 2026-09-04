# Task 84: Range-Safe Translation Recovery

## Milestone

M84

## Depends On

M83

## Goal

Prevent narrowed translation retries from reusing or overwriting unrelated chunk checkpoints, and prevent EPUB reconstruction from skipping incomplete chapters or mutating outputs before completeness is known.

## Scope

- Treat stored chunk bounds as part of runtime checkpoint compatibility without changing the database schema.
- Audit final translation artifacts before a completed translation chunk is reused.
- Preserve incompatible checkpoint rows while still executing the requested retry scope.
- Preflight every rebuild chapter before reconstruction output mutation.
- Enforce rebuild gates in direct CLI and TUI dispatch.
- Document diagnosis and recovery for chapters whose source JSON exists but final translation blocks are missing.

## Owned Files Or Modules

- `src/resemantica/orchestration/chunk_checkpoints.py`
- `src/resemantica/orchestration/runner.py`
- `src/resemantica/epub/rebuild.py`
- `src/resemantica/cli.py`
- `src/resemantica/tui/adapter.py`
- Orchestration, EPUB, CLI, and TUI regression tests
- Translation recovery and reconstruction documentation

## Interfaces To Satisfy

- Existing checkpoint schema and command syntax remain unchanged.
- A completed translation chunk is reusable only when its stored bounds cover the requested chunk and its final artifacts are complete.
- Incompatible retry ranges cannot corrupt an existing chunk checkpoint row.
- CLI and TUI rebuilds cannot bypass stage gates.
- Rebuild preflight failure preserves existing reconstruction outputs.

## Tests Or Smoke Checks

- `uv run --extra dev pytest tests\orchestration tests\epub tests\cli tests\tui -q`
- `uv run --extra dev ruff check src\resemantica tests`
- `uv run --extra dev mypy src\resemantica`
- `uv run --extra dev pytest tests -q`
- `git diff --check`
- `uv run rsem run retry-failed -r 1 -R 001 -c resemantica-pilot.toml -t translate-range -n`

## Done Criteria

- Shifted and partial retry ranges cannot inherit completion from the same numeric chunk index.
- Exact or covering completed checkpoints still resume efficiently when artifacts are complete.
- Missing final blocks remain discoverable by `retry-failed` even when checkpoint status says success.
- Reconstruction fails before filesystem mutation when any required final block is missing.
- The pilot dry-run reports the complete recovery set before model-backed repair begins.
