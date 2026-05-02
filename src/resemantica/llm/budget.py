from __future__ import annotations

import re
from dataclasses import dataclass

from resemantica.llm.tokens import count_tokens
from resemantica.settings import AppConfig


@dataclass(slots=True)
class PromptBudgetError(ValueError):
    stage_name: str
    chapter_number: int | None
    token_count: int
    max_tokens: int

    def __str__(self) -> str:
        chapter = "" if self.chapter_number is None else f" chapter={self.chapter_number}"
        return (
            f"prompt_budget_exceeded: stage={self.stage_name}{chapter} "
            f"tokens={self.token_count} max={self.max_tokens}"
        )


@dataclass(slots=True)
class TextChunk:
    chunk_index: int
    chunk_count: int
    text: str


def ensure_prompt_within_budget(
    prompt: str,
    *,
    config: AppConfig,
    stage_name: str,
    chapter_number: int | None = None,
    max_tokens: int | None = None,
) -> int:
    token_count = count_tokens(prompt)
    limit = max_tokens if max_tokens is not None else config.budget.max_context_per_pass
    if token_count > limit:
        raise PromptBudgetError(
            stage_name=stage_name,
            chapter_number=chapter_number,
            token_count=token_count,
            max_tokens=limit,
        )
    return token_count


def _split_units(text: str) -> list[str]:
    paragraphs = re.split(r"(\n{2,})", text)
    if len(paragraphs) > 1:
        units: list[str] = []
        current = ""
        for part in paragraphs:
            current += part
            if not part.startswith("\n"):
                units.append(current)
                current = ""
        if current:
            units.append(current)
        return [unit for unit in units if unit]

    sentence_units = re.findall(r"[^。！？!?\.]+[。！？!?\.]?\s*", text)
    return [unit for unit in sentence_units if unit] or [text]


def _slice_oversized_unit(unit: str, max_tokens: int) -> list[str]:
    if count_tokens(unit) <= max_tokens:
        return [unit]

    slices: list[str] = []
    remaining = unit
    while remaining:
        low = 1
        high = len(remaining)
        best = 1
        while low <= high:
            midpoint = (low + high) // 2
            candidate = remaining[:midpoint]
            if count_tokens(candidate) <= max_tokens:
                best = midpoint
                low = midpoint + 1
            else:
                high = midpoint - 1
        slices.append(remaining[:best])
        remaining = remaining[best:]
    return slices


def chunk_text_for_prompt(
    text: str,
    *,
    config: AppConfig,
    static_prompt_tokens: int,
    max_tokens: int | None = None,
) -> list[TextChunk]:
    cleaned = text.strip()
    if not cleaned:
        return []

    limit = max_tokens if max_tokens is not None else config.budget.max_context_per_pass
    max_text_tokens = limit - static_prompt_tokens
    if max_text_tokens <= 0:
        raise PromptBudgetError(
            stage_name="chunk_text_for_prompt",
            chapter_number=None,
            token_count=static_prompt_tokens,
            max_tokens=limit,
        )

    if count_tokens(cleaned) <= max_text_tokens:
        return [TextChunk(chunk_index=1, chunk_count=1, text=cleaned)]

    chunks: list[str] = []
    current = ""
    for unit in _split_units(cleaned):
        pieces = _slice_oversized_unit(unit, max_text_tokens)
        for piece in pieces:
            candidate = current + piece
            if current and count_tokens(candidate) > max_text_tokens:
                chunks.append(current.strip())
                current = piece
            else:
                current = candidate
    if current.strip():
        chunks.append(current.strip())

    chunk_count = len(chunks)
    return [
        TextChunk(chunk_index=index, chunk_count=chunk_count, text=chunk)
        for index, chunk in enumerate(chunks, start=1)
        if chunk
    ]
