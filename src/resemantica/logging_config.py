from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

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

_stderr_config: dict[str, Any] | None = None


def configure_logging(
    *,
    verbosity: int = 0,
    artifacts_dir: Path,
    run_id: str | None = None,
) -> None:
    """Configure loguru console and structured JSON file logging."""
    global _stderr_config
    effective_verbosity = min(max(verbosity, 0), 4)
    logger.remove()
    handler_id = logger.add(
        sys.stderr,
        level=_CONSOLE_LEVELS[effective_verbosity],
        format=_CONSOLE_FORMATS[effective_verbosity],
    )
    _stderr_config = {
        "id": handler_id,
        "level": _CONSOLE_LEVELS[effective_verbosity],
        "format": _CONSOLE_FORMATS[effective_verbosity],
    }

    if not artifacts_dir.exists():
        return

    logs_dir = artifacts_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        logs_dir / f"{run_id or 'session'}.jsonl",
        level="DEBUG",
        serialize=True,
    )


def replace_stderr_sink(sink_fn: Callable[[str], object], fmt: str = "{message}") -> None:
    """Replace stderr handler with a callable sink (keeps same level threshold)."""
    global _stderr_config
    if _stderr_config and _stderr_config.get("id") is not None:
        logger.remove(_stderr_config["id"])
    _stderr_config["id"] = logger.add(
        sink_fn,
        level=_stderr_config["level"],
        format=fmt,
    )


def restore_stderr_sink() -> None:
    """Remove custom sink and re-add raw stderr handler with original level and format."""
    global _stderr_config
    if _stderr_config and _stderr_config.get("id") is not None:
        logger.remove(_stderr_config["id"])
    _stderr_config["id"] = logger.add(
        sys.stderr,
        level=_stderr_config["level"],
        format=_stderr_config["format"],
    )
