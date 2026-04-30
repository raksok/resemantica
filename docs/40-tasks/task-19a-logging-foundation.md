# Task 19a: Logging Foundation

## Milestone And Depends On

Milestone: M19

Depends on: M18

## Goal
Implement the LLD-00 logging foundation using loguru. This module was specified but never built. It provides console logging and JSON file logging used by all subsequent tasks.

## Scope
In:
- Add `loguru` as a direct dependency (`uv add loguru`).
- Create `src/resemantica/logging_config.py` with `configure_logging()`.
- Configure loguru with console handler (level from verbosity flag) and JSON file handler (always DEBUG+).
- Migrate existing `logging.getLogger` usage in `events.py` and `translation/pipeline.py` to `loguru.logger`.
- Remove `import logging` from migrated files.

Out:
- Adding CLI flags (`-v`/`-vv` — that is Task 19b).
- Adding EventBus progress subscriber (Task 19b).
- Adding event emissions to pipelines (Task 19c).
- Modifying TUI logging (TUI has its own display).

## Owned Files Or Modules
- `src/resemantica/logging_config.py` (new)
- `src/resemantica/orchestration/events.py` (migrate to loguru)
- `src/resemantica/translation/pipeline.py` (migrate to loguru)

## Interfaces To Satisfy
- `logging_config.configure_logging(*, verbosity: int = 0, artifacts_dir: Path, run_id: str | None = None) -> None`
- Console format at verbosity 0: `{time:HH:mm:ss} | {level:<7} | {message}`
- Console format at verbosity 1: `{time:HH:mm:ss} | {level:<7} | {name} | {message}`
- Console format at verbosity 2: `{time:HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} | {message}`
- JSON file handler writes to `artifacts/logs/{run_id or 'session'}.jsonl` using `serialize=True`.
- JSON file handler is always DEBUG+ regardless of console level.

## Tests Or Smoke Checks
- `configure_logging(verbosity=0)` — only WARNING+ messages appear in captured output.
- `configure_logging(verbosity=1)` — INFO+ messages appear.
- `configure_logging(verbosity=2)` — DEBUG+ messages appear.
- JSON file handler writes valid JSON lines to `artifacts/logs/{run_id}.jsonl`.
- JSON file handler is no-op when `artifacts_dir` does not exist (no crash, no file created).
- Existing test suite passes after `logging.getLogger` → `loguru.logger` migration.

## Done Criteria
- `loguru` is in `pyproject.toml` dependencies.
- `logging_config.configure_logging()` configures console and JSON file handlers.
- `events.py` and `translation/pipeline.py` use `loguru.logger` instead of `logging.getLogger`.
- All existing tests pass.
- Unit tests cover all three verbosity levels and JSON file output.
