from __future__ import annotations

import re
from dataclasses import dataclass

_PLACEHOLDER_RE = re.compile(r"⟦/?[A-Z]+_\d+⟧")


@dataclass(slots=True)
class RiskClassification:
    risk_score: float
    risk_class: str
    idiom_density_score: float
    title_density_score: float
    relationship_reveal_score: float
    pronoun_ambiguity_score: float
    xhtml_fragility_score: float
    entity_density_score: float

    def to_dict(self) -> dict[str, float | str]:
        return {
            "risk_score": self.risk_score,
            "risk_class": self.risk_class,
            "idiom_density_score": self.idiom_density_score,
            "title_density_score": self.title_density_score,
            "relationship_reveal_score": self.relationship_reveal_score,
            "pronoun_ambiguity_score": self.pronoun_ambiguity_score,
            "xhtml_fragility_score": self.xhtml_fragility_score,
            "entity_density_score": self.entity_density_score,
        }


def _count_placeholders(text: str) -> int:
    opening = re.findall(r"⟦[A-Z]+_\d+⟧", text)
    return len(opening)


def _count_ambiguous_pronouns(text: str) -> int:
    pronouns = re.findall(r"\b(he|she|it|they|him|her|them|his|its|their)\b", text, re.IGNORECASE)
    return len(pronouns)


def _classify_risk(risk_score: float, threshold_high: float) -> str:
    if risk_score >= threshold_high:
        return "HIGH"
    if risk_score >= 0.3:
        return "MEDIUM"
    return "LOW"


def classify_paragraph_risk(
    *,
    idiom_count: int,
    title_count: int,
    has_reveal_gated_relationship: bool,
    ambiguous_pronoun_count: int,
    placeholder_count: int,
    distinct_entity_count: int,
    threshold_high: float = 0.7,
) -> RiskClassification:
    idiom_density_score = min(1.0, idiom_count / 3.0)
    title_density_score = min(1.0, title_count / 3.0)
    relationship_reveal_score = 1.0 if has_reveal_gated_relationship else 0.0
    pronoun_ambiguity_score = min(1.0, ambiguous_pronoun_count / 2.0)
    xhtml_fragility_score = min(1.0, placeholder_count / 5.0)
    entity_density_score = min(1.0, distinct_entity_count / 4.0)

    risk_score = min(
        1.0,
        idiom_density_score * 0.20
        + title_density_score * 0.15
        + relationship_reveal_score * 0.20
        + pronoun_ambiguity_score * 0.20
        + xhtml_fragility_score * 0.15
        + entity_density_score * 0.10,
    )

    risk_class = _classify_risk(risk_score, threshold_high)

    return RiskClassification(
        risk_score=risk_score,
        risk_class=risk_class,
        idiom_density_score=idiom_density_score,
        title_density_score=title_density_score,
        relationship_reveal_score=relationship_reveal_score,
        pronoun_ambiguity_score=pronoun_ambiguity_score,
        xhtml_fragility_score=xhtml_fragility_score,
        entity_density_score=entity_density_score,
    )


def classify_paragraph_risk_from_text(
    *,
    source_text: str,
    pass2_text: str,
    idiom_count: int = 0,
    title_count: int = 0,
    has_reveal_gated_relationship: bool = False,
    distinct_entity_count: int = 0,
    threshold_high: float = 0.7,
) -> RiskClassification:
    placeholder_count = _count_placeholders(source_text)
    ambiguous_pronoun_count = _count_ambiguous_pronouns(pass2_text)

    return classify_paragraph_risk(
        idiom_count=idiom_count,
        title_count=title_count,
        has_reveal_gated_relationship=has_reveal_gated_relationship,
        ambiguous_pronoun_count=ambiguous_pronoun_count,
        placeholder_count=placeholder_count,
        distinct_entity_count=distinct_entity_count,
        threshold_high=threshold_high,
    )
