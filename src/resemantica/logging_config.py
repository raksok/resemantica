from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_CONSOLE_FORMATS = {
    0: "{time:HH:mm:ss} | {level:<7} | {message}",
    1: "{time:HH:mm:ss} | {level:<7} | {name} | {message}",
    2: "{time:HH:mm:ss.SSS} | {level:<7} | {name} | {message}",
    3: "{time:HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} | {message}",
    4: "{time:HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} | {message}",
}
_CONSOLE_LEVELS = {
    0: "WARNING",
    1: "INFO",
    2: "INFO",
    3: "DEBUG",
    4: "DEBUG",
}


def configure_logging(
    *,
    verbosity: int = 0,
    artifacts_dir: Path,
    run_id: str | None = None,
) -> None:
    """Configure loguru console and structured JSON file logging."""
    effective_verbosity = min(max(verbosity, 0), 4)
    logger.remove()
    logger.add(
        sys.stderr,
        level=_CONSOLE_LEVELS[effective_verbosity],
        format=_CONSOLE_FORMATS[effective_verbosity],
    )

    if not artifacts_dir.exists():
        return

    logs_dir = artifacts_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        logs_dir / f"{run_id or 'session'}.jsonl",
        level="DEBUG",
        serialize=True,
    )
