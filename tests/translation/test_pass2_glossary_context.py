from __future__ import annotations

import json

from resemantica.translation.pass2 import translate_pass2

_PASS2_TEMPLATE = (
    "# version: 2.1\n"
    "{GLOSSARY}\n"
    "Source: {SOURCE_TEXT}\nDraft: {DRAFT_TEXT}\n"
    "Full: {FULL_SOURCE_BLOCK}\nPrior: {PRIOR_SEGMENTS}\n\n"
    "Respond in JSON format"
)


class MockLLMClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.last_prompt = ""

    def generate_text(self, *, model_name: str, prompt: str) -> str:
        self.last_prompt = prompt
        return self.response


class TestPass2GlossaryContext:
    def test_glossary_section_in_prompt_when_provided(self) -> None:
        client = MockLLMClient(json.dumps({
            "fidelity_errors_found": False,
            "analysis": "No errors.",
            "corrected_text": "draft unchanged",
        }))
        translate_pass2(
            client=client,
            model_name="test-model",
            prompt_template=_PASS2_TEMPLATE,
            source_text="source",
            draft_text="draft",
            full_source_block="full",
            glossary="TERMINOLOGY:\n\u6218\u795e \u2192 War God (title)",
        )
        assert "War God" in client.last_prompt
        assert "TERMINOLOGY" in client.last_prompt

    def test_no_glossary_section_when_empty(self) -> None:
        client = MockLLMClient(json.dumps({
            "fidelity_errors_found": False,
            "analysis": "No errors.",
            "corrected_text": "draft unchanged",
        }))
        translate_pass2(
            client=client,
            model_name="test-model",
            prompt_template=_PASS2_TEMPLATE,
            source_text="source",
            draft_text="draft",
            full_source_block="full",
            glossary="",
        )
        assert "TERMINOLOGY" not in client.last_prompt

    def test_default_glossary_is_empty(self) -> None:
        client = MockLLMClient(json.dumps({
            "fidelity_errors_found": False,
            "analysis": "No errors.",
            "corrected_text": "draft unchanged",
        }))
        translate_pass2(
            client=client,
            model_name="test-model",
            prompt_template=_PASS2_TEMPLATE,
            source_text="source",
            draft_text="draft",
            full_source_block="full",
        )
        assert "TERMINOLOGY" not in client.last_prompt

    def test_glossary_passed_to_resegmented_call(self) -> None:
        client = MockLLMClient(json.dumps({
            "fidelity_errors_found": False,
            "analysis": "No errors.",
            "corrected_text": "segment corrected",
        }))
        translate_pass2(
            client=client,
            model_name="test-model",
            prompt_template=_PASS2_TEMPLATE,
            source_text="segment source",
            draft_text="segment draft",
            full_source_block="full block",
            prior_segment_translations=["prior segment translation"],
            glossary="TERMINOLOGY:\n\u738b\u8005 \u2192 King (title)",
        )
        assert "King" in client.last_prompt
        assert "prior segment translation" in client.last_prompt
