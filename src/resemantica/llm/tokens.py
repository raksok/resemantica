from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _cl100k_encoding() -> Any:
    try:
        import tiktoken  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency/runtime concern
        raise RuntimeError(
            "tiktoken is required for packet and bundle token budgeting. "
            "Install dependencies before running packet assembly."
        ) from exc
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    encoding = _cl100k_encoding()
    return len(encoding.encode(text))
