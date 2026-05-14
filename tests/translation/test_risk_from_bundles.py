from __future__ import annotations

from resemantica.translation.risk import classify_paragraph_risk, classify_paragraph_risk_from_text


class TestRiskFromBundles:
    def test_bundle_idiom_count_contributes_to_risk(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=3,
            title_count=0,
            has_reveal_gated_relationship=False,
            ambiguous_pronoun_count=0,
            placeholder_count=0,
            distinct_entity_count=0,
        )
        assert result.idiom_density_score == 1.0
        assert result.risk_score > 0.0

    def test_bundle_entity_count_contributes_to_risk(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=0,
            title_count=0,
            has_reveal_gated_relationship=False,
            ambiguous_pronoun_count=0,
            placeholder_count=0,
            distinct_entity_count=4,
        )
        assert result.entity_density_score == 1.0
        assert result.risk_score > 0.0

    def test_bundle_relationships_trigger_reveal_risk(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=0,
            title_count=0,
            has_reveal_gated_relationship=True,
            ambiguous_pronoun_count=0,
            placeholder_count=0,
            distinct_entity_count=0,
        )
        assert result.relationship_reveal_score == 1.0
        assert result.risk_score > 0.0

    def test_combined_bundle_data_produces_higher_risk(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=2,
            title_count=0,
            has_reveal_gated_relationship=True,
            ambiguous_pronoun_count=0,
            placeholder_count=3,
            distinct_entity_count=2,
        )
        assert result.risk_score > 0.3

    def test_fallback_to_text_when_no_bundle(self) -> None:
        result = classify_paragraph_risk_from_text(
            source_text="A simple sentence",
            pass2_text="A simple sentence",
        )
        assert result is not None
        assert result.risk_class in ("LOW", "MEDIUM", "HIGH")

    def test_bundle_zero_values_same_as_text_only(self) -> None:
        classify_paragraph_risk_from_text(
            source_text="A simple sentence.",
            pass2_text="A simple sentence.",
        )
        bundle_result = classify_paragraph_risk(
            idiom_count=0,
            title_count=0,
            has_reveal_gated_relationship=False,
            ambiguous_pronoun_count=0,
            placeholder_count=0,
            distinct_entity_count=0,
        )
        assert bundle_result.risk_score == 0.0
