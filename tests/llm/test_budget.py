from __future__ import annotations

import pytest

from resemantica.llm import budget as budget_mod
from resemantica.llm.budget import PromptBudgetError, chunk_text_for_prompt, ensure_prompt_within_budget
from resemantica.settings import AppConfig


def test_prompt_budget_accepts_under_limit_and_rejects_over_limit(monkeypatch) -> None:
    monkeypatch.setattr(budget_mod, "count_tokens", lambda text: len(text))
    config = AppConfig()
    config.budget.max_context_per_pass = 5

    assert ensure_prompt_within_budget("12345", config=config, stage_name="stage") == 5
    with pytest.raises(PromptBudgetError) as exc_info:
        ensure_prompt_within_budget("123456", config=config, stage_name="stage", chapter_number=2)

    assert "prompt_budget_exceeded" in str(exc_info.value)
    assert "chapter=2" in str(exc_info.value)


def test_chunk_text_for_prompt_is_deterministic_and_ordered(monkeypatch) -> None:
    monkeypatch.setattr(budget_mod, "count_tokens", lambda text: len(text))
    config = AppConfig()
    config.budget.max_context_per_pass = 12

    chunks = chunk_text_for_prompt(
        "alpha beta gamma delta",
        config=config,
        static_prompt_tokens=2,
    )

    assert [chunk.chunk_index for chunk in chunks] == list(range(1, len(chunks) + 1))
    assert all(chunk.chunk_count == len(chunks) for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks).replace(" ", "") == "alphabetagammadelta"
    assert all(chunk.text for chunk in chunks)


def test_ensure_prompt_within_budget_uses_max_tokens_override(monkeypatch) -> None:
    monkeypatch.setattr(budget_mod, "count_tokens", lambda text: len(text))
    config = AppConfig()
    config.budget.max_context_per_pass = 100

    assert ensure_prompt_within_budget("12345", config=config, stage_name="s", max_tokens=10) == 5
    with pytest.raises(PromptBudgetError) as exc_info:
        ensure_prompt_within_budget("12345678901", config=config, stage_name="s", max_tokens=10)
    assert "max=10" in str(exc_info.value)


def test_ensure_prompt_within_budget_falls_back_to_config(monkeypatch) -> None:
    monkeypatch.setattr(budget_mod, "count_tokens", lambda text: len(text))
    config = AppConfig()
    config.budget.max_context_per_pass = 5

    assert ensure_prompt_within_budget("12345", config=config, stage_name="s") == 5
    with pytest.raises(PromptBudgetError):
        ensure_prompt_within_budget("123456", config=config, stage_name="s")


def test_chunk_text_for_prompt_uses_max_tokens_override(monkeypatch) -> None:
    monkeypatch.setattr(budget_mod, "count_tokens", lambda text: len(text))
    config = AppConfig()
    config.budget.max_context_per_pass = 100

    chunks = chunk_text_for_prompt(
        "alpha beta gamma delta",
        config=config,
        static_prompt_tokens=2,
        max_tokens=12,
    )

    assert len(chunks) > 1
    assert "".join(chunk.text for chunk in chunks).replace(" ", "") == "alphabetagammadelta"


def test_chunk_text_for_prompt_falls_back_to_config(monkeypatch) -> None:
    monkeypatch.setattr(budget_mod, "count_tokens", lambda text: len(text))
    config = AppConfig()
    config.budget.max_context_per_pass = 100

    chunks = chunk_text_for_prompt(
        "short text",
        config=config,
        static_prompt_tokens=2,
    )

    assert len(chunks) == 1
    assert chunks[0].text == "short text"
