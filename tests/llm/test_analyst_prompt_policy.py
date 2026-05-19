from __future__ import annotations

import pytest

from resemantica.llm.prompts import load_prompt

ANTI_RESTART_PHRASES = [
    "Reason through the task once",
    "Do not restart your reasoning",
    "loop over the same uncertainty",
]


JSON_PROMPTS = [
    "summary_zh_structured.txt",
    "summary_zh_validate.txt",
    "summary_graph_continuity_update.txt",
    "glossary_evaluate.txt",
    "idiom_evaluate.txt",
    "graph_extract.txt",
    "translate_pass2.txt",
]


@pytest.mark.parametrize(
    "prompt_name",
    [
        "summary_zh_structured.txt",
        "summary_zh_validate.txt",
        "summary_story_compact.txt",
        "summary_graph_continuity_update.txt",
        "glossary_evaluate.txt",
        "idiom_evaluate.txt",
        "graph_extract.txt",
        "translate_pass2.txt",
        "translate_pass3.txt",
    ],
)
def test_analyst_prompts_include_anti_restart_instruction(prompt_name: str) -> None:
    prompt = load_prompt(prompt_name)

    for phrase in ANTI_RESTART_PHRASES:
        assert phrase in prompt.template


@pytest.mark.parametrize("prompt_name", JSON_PROMPTS)
def test_json_analyst_prompts_keep_json_only_constraints(prompt_name: str) -> None:
    prompt = load_prompt(prompt_name)

    assert "JSON" in prompt.template
    assert "markdown" in prompt.template.lower()
    assert "chain-of-thought" in prompt.template
    assert "<think>" in prompt.template


def test_structured_summary_prompt_keeps_schema_requirements() -> None:
    prompt = load_prompt("summary_zh_structured.txt")

    assert "Required keys, all present exactly once" in prompt.template
    assert "is_story_chapter must be a JSON boolean" in prompt.template
    assert "Return one JSON object only" in prompt.template


def test_validation_prompt_keeps_flags_schema() -> None:
    prompt = load_prompt("summary_zh_validate.txt")

    assert 'two keys: "flags" and "warnings"' in prompt.template
    assert '{{"flags": [], "warnings": []}}' in prompt.template


def test_graph_continuity_prompt_keeps_anchor_audit_schema() -> None:
    prompt = load_prompt("summary_graph_continuity_update.txt")

    assert '"continuity_zh"' in prompt.template
    assert '"anchor_audit"' in prompt.template
    assert "uncertain_anchor_ids" in prompt.template
    assert "Never resolve ambiguity with outside knowledge" in prompt.template


def test_evaluator_prompts_keep_array_schema() -> None:
    glossary_prompt = load_prompt("glossary_evaluate.txt")
    idiom_prompt = load_prompt("idiom_evaluate.txt")

    assert "Return a JSON array only" in glossary_prompt.template
    assert "candidate_id" in glossary_prompt.template
    assert "Return a JSON array only" in idiom_prompt.template
    assert "is_idiom" in idiom_prompt.template


def test_graph_prompt_keeps_extraction_schema() -> None:
    prompt = load_prompt("graph_extract.txt")

    assert 'two keys: "entities" and "relationships"' in prompt.template
    assert "Entities schema" in prompt.template
    assert "Relationships schema" in prompt.template


def test_pass_prompts_keep_output_contracts() -> None:
    pass2_prompt = load_prompt("translate_pass2.txt")
    pass3_prompt = load_prompt("translate_pass3.txt")

    assert '"fidelity_errors_found": boolean' in pass2_prompt.template
    assert '"corrected_text"' in pass2_prompt.template
    assert "Polish the Pass 2 output" in pass3_prompt.template
    assert "return only the final requested prose" in pass3_prompt.template
