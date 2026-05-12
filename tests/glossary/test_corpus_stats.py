
from resemantica.glossary.candidate_gen import CAT_OTHER, RawCandidate
from resemantica.glossary.corpus_stats import (
    compute_corpus_stats,
    score_candidates,
)


def test_compute_corpus_stats():
    c1 = RawCandidate("李明", "李明", ["NR"], None, CAT_OTHER, {"ner"}, appearances=2)
    c2 = RawCandidate("宗门", "宗门", ["NN"], None, CAT_OTHER, {"ngram"}, appearances=1)

    c3 = RawCandidate("李明", "李明", ["NR"], None, CAT_OTHER, {"ner"}, appearances=3)

    per_chapter = {
        1: [c1, c2],
        2: [c3]
    }

    stats = compute_corpus_stats(per_chapter)

    assert stats.total_chapters == 2
    # 李明 freq = 2 + 3 = 5
    # 宗门 freq = 1
    assert stats.term_frequency["李明"] == 5
    assert stats.term_frequency["宗门"] == 1

    # 李明 is in chap 1 and chap 2
    # 宗门 is in chap 1 only
    assert stats.document_frequency["李明"] == 2
    assert stats.document_frequency["宗门"] == 1


def test_score_candidates():
    # c_value needs lengths >= 2
    c_long = RawCandidate("无上仙门", "无上仙门", ["NN"], None, CAT_OTHER, {"ner"}, appearances=10)
    c_short = RawCandidate("仙门", "仙门", ["NN"], None, CAT_OTHER, {"ngram"}, appearances=10)

    stats = compute_corpus_stats({
        1: [c_long, c_short]
    })

    # "无上仙门" has length 4, frequency 10. no superstrings.
    # C-value = log2(4) * 10 = 2 * 10 = 20
    # "仙门" has length 2, frequency 10. "无上仙门" is superstring (freq 10).
    # count of superstrings = 1, sum of superstrings = 10.
    # C-value = log2(2) * (10 - 10) = 1 * 0 = 0.

    scored = score_candidates([c_long, c_short], stats)
    assert len(scored) == 2

    # Find which is which
    s_long = next(s for s in scored if s.raw.normalized_form == "无上仙门")
    s_short = next(s for s in scored if s.raw.normalized_form == "仙门")

    assert s_long.c_value == 20.0
    assert s_short.c_value == 0.0

    # Check that sorting is descending by composite score
    assert scored[0] == s_long
    assert scored[1] == s_short


def test_score_candidates_summary_boost():
    """Summary-verified candidate scores higher than identical non-verified."""
    c_verified = RawCandidate("青云门", "青云门", ["NR", "NR"], None, CAT_OTHER, {"ner"}, appearances=10)
    c_unverified = RawCandidate("苍云门", "苍云门", ["NR", "NR"], None, CAT_OTHER, {"ner"}, appearances=10)

    stats = compute_corpus_stats({1: [c_verified, c_unverified]})

    scored = score_candidates([c_verified, c_unverified], stats, summary_term_set={"青云门"})
    assert len(scored) == 2

    s_ver = next(s for s in scored if s.raw.normalized_form == "青云门")
    s_unv = next(s for s in scored if s.raw.normalized_form == "苍云门")

    assert s_ver.composite_score > s_unv.composite_score


def test_score_candidates_summary_boost_empty_set():
    """Empty summary_term_set produces same scores as without."""
    c = RawCandidate("青云门", "青云门", ["NR", "NR"], None, CAT_OTHER, {"ner"}, appearances=10)
    stats = compute_corpus_stats({1: [c]})

    scored_with = score_candidates([c], stats, summary_term_set=set())
    scored_without = score_candidates([c], stats)

    assert scored_with[0].composite_score == scored_without[0].composite_score
