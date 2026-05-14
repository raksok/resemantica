from __future__ import annotations

from resemantica.translation.pass1 import _clean_pass1_response


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
