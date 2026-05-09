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


def score_idiom_candidates(candidates: list[RawIdiomCandidate]) -> list[ScoredIdiomCandidate]:
    if not candidates:
        return []

    max_freq = max(candidate.appearances for candidate in candidates) or 1
    scored: list[ScoredIdiomCandidate] = []
    for candidate in candidates:
        strategy_score = min(1.0, len(candidate.strategies) / 3)
        frequency_score = candidate.appearances / max_freq
        dictionary_score = 1.0 if candidate.dictionary_match else 0.0
        c_value = math.log2(max(2, len(candidate.normalized_form))) * candidate.appearances
        composite = (0.45 * dictionary_score) + (0.3 * strategy_score) + (0.25 * frequency_score)
        scored.append(
            ScoredIdiomCandidate(
                raw=candidate,
                c_value=c_value,
                composite_score=composite,
                chapter_coverage=1 + max(0, candidate.last_seen_chapter - candidate.first_seen_chapter),
            )
        )
    return sorted(scored, key=lambda item: item.composite_score, reverse=True)
