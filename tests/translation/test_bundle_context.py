from __future__ import annotations

from resemantica.packets.models import ParagraphBundle
from resemantica.translation.bundle_context import (
    extract_glossary_target_terms_for_pass3,
    format_bundle_for_pass1,
    format_bundle_for_pass2,
    format_bundle_for_pass3,
)


def _bundle() -> ParagraphBundle:
    return ParagraphBundle(
        bundle_id="b1",
        release_id="rel",
        chapter_number=1,
        block_id="blk",
        matched_glossary_entries=[
            {
                "source_term": "战神",
                "target_term": "War God",
                "category": "title_honorific",
            }
        ],
        alias_resolutions=[{"alias_text": "老张", "entity_name": "Zhang San"}],
        matched_idioms=[
            {
                "source_text": "画蛇添足",
                "preferred_rendering_en": "gild the lily",
                "meaning_en": "to overdo something",
                "meaning_zh": "多此一举",
                "usage_notes": "Keep concise.",
            }
        ],
        local_relationships=[
            {
                "relationship_id": "r1",
                "type": "MASTER_OF",
                "source_entity_id": "e1",
                "target_entity_id": "e2",
                "lore_text": "Zhang San mentors Li Si.",
                "is_masked_identity": False,
            }
        ],
        continuity_notes=["prior chapter note"],
        retrieval_evidence_summary=["glossary:1", "graph_relationship:1"],
        risk_classification="unscored",
        packet_ref="pkt",
    )


def test_pass1_formatter_includes_existing_and_enriched_context() -> None:
    context = format_bundle_for_pass1(_bundle())

    assert "战神" in context["glossary"]
    assert "老张" in context["alias_resolutions"]
    assert "meaning_en: to overdo something" in context["matched_idioms"]
    assert "meaning_zh: 多此一举" in context["matched_idioms"]
    assert "usage_notes: Keep concise." in context["matched_idioms"]
    assert "prior chapter note" in context["continuity_notes"]


def test_pass2_formatter_includes_all_context_groups() -> None:
    context = format_bundle_for_pass2(_bundle())

    assert "TERMINOLOGY" in context["glossary"]
    assert "ALIASES" in context["alias_resolutions"]
    assert "IDIOMS" in context["matched_idioms"]
    assert "RELATIONSHIPS" in context["local_relationships"]
    assert "CONTINUITY" in context["continuity_notes"]
    assert "RETRIEVAL_EVIDENCE" in context["retrieval_evidence"]
    assert "graph_relationship:1" in context["retrieval_evidence"]


def test_pass3_formatter_and_target_extraction() -> None:
    context = format_bundle_for_pass3(_bundle())

    assert "TERMINOLOGY TO PRESERVE" in context["glossary"]
    assert "ALIASES TO PRESERVE" in context["alias_resolutions"]
    assert "IDIOM RENDERINGS TO PRESERVE" in context["matched_idioms"]
    assert "RELATIONSHIP CONSTRAINTS" in context["relationship_constraints"]
    assert extract_glossary_target_terms_for_pass3(_bundle()) == ["War God"]


def test_missing_bundle_formats_as_empty_context() -> None:
    assert all(value == "" for value in format_bundle_for_pass1(None).values())
    assert all(value == "" for value in format_bundle_for_pass2(None).values())
    assert all(value == "" for value in format_bundle_for_pass3(None).values())
    assert extract_glossary_target_terms_for_pass3(None) == []
