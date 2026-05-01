from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from resemantica.llm.client import LLMClient
from resemantica.settings import AppConfig


def _chapter_number_from_path(path: Path) -> int:
    stem = path.stem
    digits = "".join(c for c in stem if c.isdigit())
    return int(digits)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _build_llm_client(config: AppConfig, llm_client: LLMClient | None) -> LLMClient:
    if llm_client is not None:
        return llm_client
    return LLMClient(
        base_url=config.llm.base_url,
        timeout_seconds=config.llm.timeout_seconds,
        max_retries=config.llm.max_retries,
    )


def _emit(run_id: str, release_id: str, event_type: str, **kwargs: object) -> None:
    chapter_number = kwargs.pop("chapter_number", None)
    message = str(kwargs.pop("message", ""))
    severity = str(kwargs.pop("severity", "info"))
    stage_name = str(kwargs.pop("stage_name", ""))
    try:
        from resemantica.orchestration.events import emit_event

        emit_event(
            run_id,
            release_id,
            event_type,
            stage_name,
            chapter_number=chapter_number if isinstance(chapter_number, int) else None,
            severity=severity,
            message=message,
            payload=dict(kwargs),
        )
    except Exception as exc:
        logger.debug("Failed to emit tracking event: {}", exc)
