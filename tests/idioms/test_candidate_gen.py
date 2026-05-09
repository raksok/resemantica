from __future__ import annotations

from resemantica.idioms.candidate_gen import (
    generate_chapter_idiom_candidates,
    merge_across_chapters,
)


def test_lexicon_exact_match_generates_idiom_without_llm() -> None:
    candidates = generate_chapter_idiom_candidates(
        chapter_number=3,
        source_text="他这一招可谓一箭双雕，既救了人，也赢了局。",
    )

    match = next(candidate for candidate in candidates if candidate.surface_form == "一箭双雕")
    assert match.dictionary_match is True
    assert "lexicon" in match.strategies
    assert match.appearances == 1
    assert match.first_seen_chapter == 3
    assert match.idiomatic_meaning_zh


def test_repeated_four_character_expression_is_mined() -> None:
    candidates = generate_chapter_idiom_candidates(
        chapter_number=1,
        source_text="他孤苦伶仃地走着。多年后，仍是孤苦伶仃。",
    )

    match = next(candidate for candidate in candidates if candidate.surface_form == "孤苦伶仃")
    assert "four_char" in match.strategies
    assert match.appearances == 2


def test_merge_across_chapters_accumulates_frequency_and_strategies() -> None:
    first = generate_chapter_idiom_candidates(
        chapter_number=1,
        source_text="此计一箭双雕。",
    )
    second = generate_chapter_idiom_candidates(
        chapter_number=2,
        source_text="这一招也是一箭双雕。",
    )

    accumulator = merge_across_chapters({}, first)
    merge_across_chapters(accumulator, second)

    merged = accumulator["一箭双雕"]
    assert merged.appearances == 2
    assert merged.first_seen_chapter == 1
    assert merged.last_seen_chapter == 2
    assert "lexicon" in merged.strategies
    assert len(merged.context_snippets) >= 2
