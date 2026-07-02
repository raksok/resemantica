from __future__ import annotations

import json

import pytest

from resemantica.llm.budget import PromptBudgetError
from resemantica.settings import AppConfig, BudgetConfig
from resemantica.translation.pass1 import translate_pass1
from resemantica.translation.pass2 import translate_pass2
from resemantica.translation.pass3 import translate_pass3


class GuardedClient:
    def __init__(self, response: str = "ok") -> None:
        self.response = response
        self.calls = 0

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        self.calls += 1
        return self.response


def _tiny_budget_config() -> AppConfig:
    return AppConfig(budget=BudgetConfig(max_context_per_pass=1))


def test_pass1_prompt_budget_failure_before_llm_call() -> None:
    client = GuardedClient()

    with pytest.raises(PromptBudgetError, match="stage=translate.pass1 chapter=7"):
        translate_pass1(
            client=client,
            model_name="model",
            prompt_template="{GLOSSARY}\n{SOURCE_TEXT}",
            source_text="source text that is too long for the tiny test budget",
            glossary="term -> Term",
            config=_tiny_budget_config(),
            chapter_number=7,
        )

    assert client.calls == 0


def test_pass2_prompt_budget_failure_before_llm_call() -> None:
    client = GuardedClient(json.dumps({"fidelity_errors_found": False}))

    with pytest.raises(PromptBudgetError, match="stage=translate.pass2 chapter=8"):
        translate_pass2(
            client=client,
            model_name="model",
            prompt_template="{SOURCE_TEXT}\n{DRAFT_TEXT}\n{FULL_SOURCE_BLOCK}",
            source_text="source text that is too long for the tiny test budget",
            draft_text="draft",
            full_source_block="full source block",
            config=_tiny_budget_config(),
            chapter_number=8,
        )

    assert client.calls == 0


def test_pass3_prompt_budget_failure_before_llm_call() -> None:
    client = GuardedClient()

    with pytest.raises(PromptBudgetError, match="stage=translate.pass3 chapter=9"):
        translate_pass3(
            client=client,
            model_name="model",
            prompt_template="{SOURCE_TEXT}\n{PASS2_OUTPUT}\n{GLOSSARY}",
            source_text="source text that is too long for the tiny test budget",
            pass2_output="pass2 output",
            glossary_text="term -> Term",
            config=_tiny_budget_config(),
            chapter_number=9,
        )

    assert client.calls == 0


def test_translation_prompt_under_budget_calls_llm() -> None:
    client = GuardedClient("Translated output")

    result = translate_pass1(
        client=client,
        model_name="model",
        prompt_template="{SOURCE_TEXT}",
        source_text="source",
        config=AppConfig(budget=BudgetConfig(max_context_per_pass=1_000)),
        chapter_number=1,
    )

    assert result == "Translated output"
    assert client.calls == 1
