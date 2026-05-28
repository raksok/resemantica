
from resemantica.glossary.candidate_gen import CAT_OTHER, RawCandidate
from resemantica.glossary.corpus_stats import (
    compute_c_value,
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


def test_score_candidates_progress_callback_does_not_change_scores():
    c_long = RawCandidate("无上仙门", "无上仙门", ["NN"], None, CAT_OTHER, {"ner"}, appearances=10)
    c_short = RawCandidate("仙门", "仙门", ["NN"], None, CAT_OTHER, {"ngram"}, appearances=10)
    stats = compute_corpus_stats({1: [c_long, c_short]})
    progress_events: list[dict[str, object]] = []

    scored_without = score_candidates([c_long, c_short], stats)
    scored_with = score_candidates([c_long, c_short], stats, progress_callback=progress_events.append)

    assert [
        (item.raw.normalized_form, item.tf_idf, item.c_value, item.composite_score)
        for item in scored_with
    ] == [
        (item.raw.normalized_form, item.tf_idf, item.c_value, item.composite_score)
        for item in scored_without
    ]
    assert progress_events


def test_score_candidates_progress_callback_reports_c_value_and_composite_phases():
    candidates = [
        RawCandidate("无上仙门", "无上仙门", ["NN"], None, CAT_OTHER, {"ner"}, appearances=10),
        RawCandidate("仙门", "仙门", ["NN"], None, CAT_OTHER, {"ngram"}, appearances=10),
    ]
    stats = compute_corpus_stats({1: candidates})
    progress_events: list[dict[str, object]] = []

    score_candidates(candidates, stats, progress_callback=progress_events.append)

    assert ("c_value", "started") in {
        (event["phase"], event["event"]) for event in progress_events
    }
    assert ("c_value", "progress") in {
        (event["phase"], event["event"]) for event in progress_events
    }
    assert ("c_value", "completed") in {
        (event["phase"], event["event"]) for event in progress_events
    }
    assert ("composite", "started") in {
        (event["phase"], event["event"]) for event in progress_events
    }
    assert ("composite", "progress") in {
        (event["phase"], event["event"]) for event in progress_events
    }
    assert ("composite", "completed") in {
        (event["phase"], event["event"]) for event in progress_events
    }


def test_compute_c_value_small_candidate_set_emits_final_progress():
    candidate = RawCandidate("青云门", "青云门", ["NR"], None, CAT_OTHER, {"ner"}, appearances=1)
    progress_events: list[dict[str, object]] = []

    compute_c_value([candidate], {"青云门": 1}, progress_callback=progress_events.append)

    final_progress = [
        event
        for event in progress_events
        if event["event"] == "progress" and event["phase"] == "c_value"
    ][-1]
    assert final_progress["processed_count"] == 1
    assert final_progress["total_count"] == 1
    assert final_progress["percent"] == 100.0
