# LLD 19a: Logging Foundation

## Summary
Implement the logging foundation specified in LLD-00 using loguru. This creates the `logging_config.configure_logging()` module that was designed but never built, providing console and JSON file logging for all downstream tasks.

## Problem Statement
LLD-00 specifies `logging_config.configure_logging()` with loguru console and JSON file logging, but the module was never implemented. The codebase has 10 `logging.getLogger` calls that are effectively dead code (Python defaults to WARNING+ only with no configuration). Operators running long CLI sessions see zero log output.

## Technical Design

### 1. Dependency
Add `loguru` as a direct dependency via `uv add loguru`.

### 2. Module: `logging_config.py`
```python
def configure_logging(
    *,
    verbosity: int = 0,           # 0=WARNING, 1=INFO, 2=DEBUG
    artifacts_dir: Path,
    run_id: str | None = None,
) -> None:
```

**Console handler** (loguru `sys.stderr`):
- Removes loguru's default handler first.
- Level mapping: 0 → WARNING, 1 → INFO, 2 → DEBUG.
- Format by verbosity:
  - 0: `{time:HH:mm:ss} | {level:<7} | {message}`
  - 1: `{time:HH:mm:ss} | {level:<7} | {name} | {message}`
  - 2: `{time:HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} | {message}`
- Colorized output (loguru default).

**JSON file handler:**
- Always DEBUG+ regardless of console level.
- Path: `artifacts/logs/{run_id or 'session'}.jsonl`.
- Uses loguru's `serialize=True` for structured JSON lines.
- Append-oriented — never overwrites previous run logs.
- Created only when `artifacts_dir` exists (no-op otherwise, no crash).
- `rotation` and `retention` are not configured initially (YAGNI).

### 3. Migration of Existing Code
- `orchestration/events.py`: replace `import logging` + `logging.getLogger(__name__)` with `from loguru import logger`.
- `translation/pipeline.py`: same replacement.
- Both files use `logger.warning(...)` and `logger.info(...)` — loguru's API is a superset, so no call-site changes needed.

## Data Flow
1. CLI entry point calls `configure_logging(verbosity=N, artifacts_dir=..., run_id=...)`.
2. Loguru removes default handler, adds console handler at mapped level.
3. If artifacts dir exists, adds JSON file handler at DEBUG.
4. All `loguru.logger` calls throughout the codebase emit to configured handlers.
5. JSON logs accumulate under `artifacts/logs/` for post-mortem analysis.

## Out of Scope
- CLI `-v`/`-vv` flag wiring (Task 19b).
- EventBus subscriber or progress bars (Task 19b).
- Pipeline event emissions (Task 19c).
- MLflow or external log shipping.
- Log rotation or retention policies.
