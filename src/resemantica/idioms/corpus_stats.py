from __future__ import annotations

import math
from dataclasses import dataclass

from resemantica.idioms.candidate_gen import RawIdiomCandidate


@dataclass(slots=True)
class ScoredIdiomCandidate:
    raw: RawIdiomCandidate
    c_value: float
    composite_score: float
    chapter_coverage: int


def score_idiom_candidates(
    candidates: list[RawIdiomCandidate],
    summary_term_set: set[str] | None = None,
) -> list[ScoredIdiomCandidate]:
    if not candidates:
        return []

    max_freq = max(candidate.appearances for candidate in candidates) or 1
    max_c_value = max(
        (math.log2(max(2, len(c.normalized_form))) * c.appearances for c in candidates),
        default=1.0,
    )
    if max_c_value <= 0:
        max_c_value = 1.0

    scored: list[ScoredIdiomCandidate] = []
    for candidate in candidates:
        strategy_score = min(1.0, len(candidate.strategies) / 3)
        frequency_score = candidate.appearances / max_freq
        dictionary_score = 1.0 if candidate.dictionary_match else 0.0
        c_value = math.log2(max(2, len(candidate.normalized_form))) * candidate.appearances
        c_value_norm = c_value / max_c_value

        composite = (
            0.35 * dictionary_score + 0.25 * strategy_score
            + 0.20 * frequency_score + 0.20 * c_value_norm
        )

        # Strategy-specific multipliers
        has_lexicon = "lexicon" in candidate.strategies
        has_four_char = "four_char" in candidate.strategies and candidate.dictionary_match
        has_fixed = "fixed_pattern" in candidate.strategies
        if has_lexicon:
            composite *= 1.15
        elif has_four_char:
            composite *= 1.1
        elif has_fixed and not candidate.dictionary_match:
            composite *= 0.9

        # Summary-verified term boost
        if summary_term_set and candidate.normalized_form in summary_term_set:
            composite *= 1.15

        scored.append(
            ScoredIdiomCandidate(
                raw=candidate,
                c_value=c_value,
                composite_score=composite,
                chapter_coverage=1 + max(0, candidate.last_seen_chapter - candidate.first_seen_chapter),
            )
        )
    return sorted(scored, key=lambda item: item.composite_score, reverse=True)
