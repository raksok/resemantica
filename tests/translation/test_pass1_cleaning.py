from __future__ import annotations

from resemantica.translation.pass1 import (
    _clean_pass1_response,
    _translate_pass1_with_diagnostics,
    translate_pass1,
)


class TestPass1Cleaning:
    def test_think_tags_stripped(self) -> None:
        result = _clean_pass1_response("<think>Let me translate</think>Hello world")
        assert result == "Hello world"

    def test_thought_tags_stripped(self) -> None:
        result = _clean_pass1_response("<thought>reasoning</thought>The text")
        assert result == "The text"

    def test_label_prefix_stripped(self) -> None:
        result = _clean_pass1_response("Translation: Hello world")
        assert result == "Hello world"

    def test_markdown_bold_stripped(self) -> None:
        result = _clean_pass1_response("**Hello** world")
        assert result == "Hello world"

    def test_markdown_italic_stripped(self) -> None:
        result = _clean_pass1_response("*Hello* world")
        assert result == "Hello world"

    def test_smart_quotes_stripped(self) -> None:
        result = _clean_pass1_response('\u201cHello\u201d')
        assert result == "Hello"

    def test_chinese_characters_reject_to_empty(self) -> None:
        result = _clean_pass1_response("This has \u4f60 Chinese chars")
        assert result == ""

    def test_clean_english_passes_through(self) -> None:
        result = _clean_pass1_response("Hello world. This is a test.")
        assert result == "Hello world. This is a test."

    def test_empty_input_returns_empty(self) -> None:
        result = _clean_pass1_response("")
        assert result == ""


class _RetryClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.prompts: list[str] = []

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        self.prompts.append(prompt)
        return next(self.responses)


def test_pass1_retries_empty_or_chinese_output_with_english_only_instruction() -> None:
    client = _RetryClient(["", "仍然是中文", "Complete English translation."])

    result = translate_pass1(
        client=client,  # type: ignore[arg-type]
        model_name="translator",
        prompt_template="SOURCE_TEXT: {SOURCE_TEXT}",
        source_text="中文原文",
    )

    assert result == "Complete English translation."
    assert len(client.prompts) == 3
    assert all("English only" in prompt for prompt in client.prompts[1:])
    assert "仍然是中文" not in client.prompts[1]
    assert "仍然是中文" in client.prompts[2]
    assert "PREVIOUS_RESPONSE" in client.prompts[2]


def test_pass1_retry_exhaustion_returns_empty() -> None:
    client = _RetryClient(["", "中文", "仍是中文"])

    result = translate_pass1(
        client=client,  # type: ignore[arg-type]
        model_name="translator",
        prompt_template="SOURCE_TEXT: {SOURCE_TEXT}",
        source_text="中文原文",
    )

    assert result == ""
    assert len(client.prompts) == 3


def test_pass1_retry_exhaustion_reports_untranslated_chinese_spans() -> None:
    client = _RetryClient(
        [
            "Mostly English with 桐叶 left.",
            "Still English with 桐叶 left.",
            "Again English with 桐叶 left.",
        ]
    )

    result = _translate_pass1_with_diagnostics(
        client=client,  # type: ignore[arg-type]
        model_name="translator",
        prompt_template="SOURCE_TEXT: {SOURCE_TEXT}",
        source_text="桐叶洲原文",
    )

    assert result.text == ""
    assert result.untranslated_spans == ("桐叶",)
    assert result.failure_reason == "Candidate output contains untranslated Chinese spans: 桐叶."
    assert "Mostly English with 桐叶 left." in client.prompts[1]
    assert "Still English with 桐叶 left." in client.prompts[2]
