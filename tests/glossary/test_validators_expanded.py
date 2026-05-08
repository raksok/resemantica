import json

from resemantica.glossary.models import GlossaryCandidate
from resemantica.glossary.validators import apply_deterministic_filter
from resemantica.settings import GlossaryConfig


def _make_candidate(
    term: str,
    pos_tags: list[str] | None = None,
    corpus_score: float | None = None
) -> GlossaryCandidate:
    return GlossaryCandidate(
        candidate_id="test",
        release_id="test",
        source_term=term,
        normalized_source_term=term,
        category="character",
        source_language="zh",
        first_seen_chapter=1,
        last_seen_chapter=1,
        appearance_count=1,
        evidence_snippet="",
        discovery_run_id="run",
        candidate_status="discovered",
        candidate_translation_en=None,
        normalized_target_term=None,
        translation_run_id=None,
        validation_status="pending",
        conflict_reason=None,
        pos_tags=json.dumps(pos_tags) if pos_tags else None,
        corpus_score=corpus_score,
        schema_version=1,
    )


def test_apply_deterministic_filter_min_max_length():
    config = GlossaryConfig(min_term_length=2, max_term_length=5, min_corpus_score=0.0)

    # Valid
    c1 = _make_candidate("李明")
    # Too short
    c2 = _make_candidate("李")
    # Too long
    c3 = _make_candidate("这是一个非常长的名字哦")

    filtered = apply_deterministic_filter([c1, c2, c3], config=config)

    assert filtered[0].candidate_status == "discovered"

    assert filtered[1].candidate_status == "filtered"
    assert "min_length" in filtered[1].conflict_reason

    assert filtered[2].candidate_status == "filtered"
    assert "max_length" in filtered[2].conflict_reason


def test_apply_deterministic_filter_punct_noise():
    config = GlossaryConfig(min_term_length=1, max_term_length=20, min_corpus_score=0.0)

    c1 = _make_candidate("李明")
    c2 = _make_candidate("...")
    c3 = _make_candidate("123 ")

    filtered = apply_deterministic_filter([c1, c2, c3], config=config)

    assert filtered[0].candidate_status == "discovered"

    assert filtered[1].candidate_status == "filtered"
    assert "punctuation_noise" in filtered[1].conflict_reason

    assert filtered[2].candidate_status == "filtered"
    assert "punctuation_noise" in filtered[2].conflict_reason


def test_apply_deterministic_filter_pos_generic():
    config = GlossaryConfig(min_term_length=1, max_term_length=20, min_corpus_score=0.0)

    # Noun
    c1 = _make_candidate("山脉", pos_tags=["NN"])
    # Verb + Adverb
    c2 = _make_candidate("忽然去", pos_tags=["AD", "VV"])

    filtered = apply_deterministic_filter([c1, c2], config=config)

    assert filtered[0].candidate_status == "discovered"

    assert filtered[1].candidate_status == "filtered"
    assert "pos_generic" in filtered[1].conflict_reason


def test_apply_deterministic_filter_low_score():
    config = GlossaryConfig(min_term_length=1, max_term_length=20, min_corpus_score=0.5)

    c1 = _make_candidate("李明", corpus_score=0.8)
    c2 = _make_candidate("王五", corpus_score=0.2)

    filtered = apply_deterministic_filter([c1, c2], config=config)

    assert filtered[0].candidate_status == "discovered"

    assert filtered[1].candidate_status == "filtered"
    assert "low_score" in filtered[1].conflict_reason


def test_apply_deterministic_filter_common_word(monkeypatch):
    import resemantica.glossary.validators as validators
    monkeypatch.setattr(validators, "_COMMON_WORDS", {"我们", "非常"})

    config = GlossaryConfig(min_term_length=1, max_term_length=20, min_corpus_score=0.0)

    c1 = _make_candidate("李明")
    c2 = _make_candidate("非常")

    filtered = apply_deterministic_filter([c1, c2], config=config)

    assert filtered[0].candidate_status == "discovered"

    assert filtered[1].candidate_status == "filtered"
    assert "common_word" in filtered[1].conflict_reason
