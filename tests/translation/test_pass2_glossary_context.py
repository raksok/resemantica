from __future__ import annotations

import json

from resemantica.translation.pass2 import render_pass2_batch_prompt, translate_pass2

_PASS2_TEMPLATE = (
    "# version: 2.2\n"
    "{GLOSSARY}\n"
    "{ALIAS_RESOLUTIONS}\n"
    "{MATCHED_IDIOMS}\n"
    "{LOCAL_RELATIONSHIPS}\n"
    "{CONTINUITY_NOTES}\n"
    "{RETRIEVAL_EVIDENCE}\n"
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

    def test_richer_context_sections_in_prompt(self) -> None:
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
            glossary="TERMINOLOGY:\n战神 → War God (title_honorific)",
            alias_resolutions="ALIASES:\n老张 → Zhang San",
            matched_idioms="IDIOMS:\n画蛇添足 → gild the lily | meaning_en: to overdo something",
            local_relationships="RELATIONSHIPS:\ne1 MASTER_OF e2",
            continuity_notes="CONTINUITY:\nprior chapter note",
            retrieval_evidence="RETRIEVAL_EVIDENCE:\ngraph_relationship:1",
        )

        assert "ALIASES" in client.last_prompt
        assert "meaning_en: to overdo something" in client.last_prompt
        assert "RELATIONSHIPS" in client.last_prompt
        assert "prior chapter note" in client.last_prompt
        assert "graph_relationship:1" in client.last_prompt

    def test_resegmented_call_receives_richer_context(self) -> None:
        client = MockLLMClient(json.dumps({
            "fidelity_errors_found": False,
            "analysis": "No errors.",
            "corrected_text": "segment unchanged",
        }))
        translate_pass2(
            client=client,
            model_name="test-model",
            prompt_template=_PASS2_TEMPLATE,
            source_text="segment source",
            draft_text="segment draft",
            full_source_block="full block",
            prior_segment_translations=["prior segment translation"],
            alias_resolutions="ALIASES:\n阿三 → Zhang San",
            matched_idioms="IDIOMS:\n胸有成竹 → have a plan",
            local_relationships="RELATIONSHIPS:\ne1 ALLY_OF e2",
            continuity_notes="CONTINUITY:\nkeep tone steady",
            retrieval_evidence="RETRIEVAL_EVIDENCE:\nidiom:1",
        )

        assert "阿三" in client.last_prompt
        assert "胸有成竹" in client.last_prompt
        assert "ALLY_OF" in client.last_prompt
        assert "prior segment translation" in client.last_prompt

    def test_empty_context_does_not_inject_section_labels(self) -> None:
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
        assert "ALIASES" not in client.last_prompt
        assert "IDIOMS" not in client.last_prompt
        assert "RELATIONSHIPS" not in client.last_prompt
        assert "RETRIEVAL_EVIDENCE" not in client.last_prompt

    def test_batched_context_is_rendered_in_input_json(self) -> None:
        prompt = render_pass2_batch_prompt(
            prompt_template="Audit batch\n{BATCH_JSON}",
            batch_items=[
                {
                    "block_id": "ch001_blk001",
                    "source_text": "source",
                    "draft_text": "draft",
                    "full_source_block": "source",
                    "prior_segments": [],
                    "glossary": "TERMINOLOGY:\n战神 -> War God",
                    "alias_resolutions": "ALIASES:\n老张 -> Zhang San",
                    "matched_idioms": "IDIOMS:\n胸有成竹 -> have a plan",
                    "local_relationships": "RELATIONSHIPS:\ne1 ALLY_OF e2",
                    "continuity_notes": "CONTINUITY:\nkeep tone steady",
                    "retrieval_evidence": "RETRIEVAL_EVIDENCE:\nidiom:1",
                }
            ],
        )

        assert "War God" in prompt
        assert "Zhang San" in prompt
        assert "have a plan" in prompt
        assert "ALLY_OF" in prompt
        assert "RETRIEVAL_EVIDENCE" in prompt
