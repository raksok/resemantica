from __future__ import annotations

from resemantica.glossary.candidate_gen import (
    CAT_CHARACTER,
    CAT_CONCEPT,
    CAT_FACTION,
    CAT_LOCATION,
    CAT_OTHER,
    RawCandidate,
    extract_heuristic_patterns,
    extract_ner_candidates,
    extract_pos_noun_phrases,
    extract_summary_terms,
    extract_webnovel_dict,
    merge_across_chapters,
    merge_candidates,
)
from resemantica.glossary.segmenter import SegmentedToken


def test_extract_ner_candidates():
    tokens = [
        SegmentedToken(text="李", pos="NR", ner="PERSON", offset_start=0, offset_end=1),
        SegmentedToken(text="明", pos="NR", ner="PERSON", offset_start=1, offset_end=2),
        SegmentedToken(text="去", pos="VV", ner=None, offset_start=2, offset_end=3),
        SegmentedToken(text="北", pos="NR", ner="LOC", offset_start=3, offset_end=4),
        SegmentedToken(text="京", pos="NR", ner="LOC", offset_start=4, offset_end=5),
    ]
    text = "李明去北京"
    candidates = extract_ner_candidates(tokens, text)

    assert len(candidates) == 2
    assert candidates[0].surface_form == "李明"
    assert candidates[0].type_prior == CAT_CHARACTER
    assert candidates[0].ner_label == "PERSON"

    assert candidates[1].surface_form == "北京"
    assert candidates[1].type_prior == CAT_LOCATION
    assert candidates[1].ner_label == "LOC"


def test_extract_pos_noun_phrases():
    tokens = [
        SegmentedToken(text="青云", pos="NN", ner=None, offset_start=0, offset_end=2),
        SegmentedToken(text="山脉", pos="NN", ner=None, offset_start=2, offset_end=4),
        SegmentedToken(text="在", pos="P", ner=None, offset_start=4, offset_end=5),
    ]
    text = "青云山脉在"
    candidates = extract_pos_noun_phrases(tokens, text)

    # "青云", "青云山脉", "山脉"
    # Wait, the extractor finds sequences of nouns.
    # It finds "青云山脉" because both are NN.
    surfaces = [c.surface_form for c in candidates]
    assert "青云山脉" in surfaces


def test_extract_heuristic_patterns():
    tokens = [
        SegmentedToken(text="紫", pos="JJ", ner=None, offset_start=0, offset_end=1),
        SegmentedToken(text="霄", pos="NN", ner=None, offset_start=1, offset_end=2),
        SegmentedToken(text="宗", pos="NN", ner=None, offset_start=2, offset_end=3),
    ]
    text = "紫霄宗"
    candidates = extract_heuristic_patterns(tokens, text)

    # "紫霄宗" ends with "宗" -> faction
    factions = [c for c in candidates if c.surface_form == "紫霄宗"]
    assert len(factions) == 1
    assert factions[0].type_prior == CAT_FACTION


def test_extract_webnovel_dict(monkeypatch):
    monkeypatch.setattr("resemantica.glossary.candidate_gen.WEBNOVEL_DICT", {"灵气", "修真"})

    tokens = [
        SegmentedToken(text="修", pos="V", ner=None, offset_start=0, offset_end=1),
        SegmentedToken(text="真", pos="N", ner=None, offset_start=1, offset_end=2),
    ]
    text = "修真"
    candidates = extract_webnovel_dict(tokens, text)
    assert len(candidates) == 1
    assert candidates[0].surface_form == "修真"
    assert candidates[0].type_prior == CAT_CONCEPT


def test_merge_candidates():
    c1 = RawCandidate("李明", "李明", ["NR", "NR"], "PERSON", CAT_CHARACTER, {"ner"})
    c2 = RawCandidate("李明", "李明", ["NR", "NR"], None, CAT_OTHER, {"pos_np"})

    merged = merge_candidates([c1, c2])
    assert len(merged) == 1
    assert merged[0].surface_form == "李明"
    assert merged[0].type_prior == CAT_CHARACTER
    assert merged[0].ner_label == "PERSON"
    assert merged[0].appearances == 2
    assert "ner" in merged[0].strategies
    assert "pos_np" in merged[0].strategies


def test_merge_across_chapters():
    c1_ch1 = RawCandidate("李明", "李明", ["NR", "NR"], "PERSON", CAT_CHARACTER, {"ner"}, appearances=2)
    c2_ch1 = RawCandidate("宗门", "宗门", ["NN"], None, CAT_OTHER, {"ngram"}, appearances=1)

    c1_ch2 = RawCandidate("李明", "李明", ["NR", "NR"], None, CAT_OTHER, {"pos_np"}, appearances=3)
    c3_ch2 = RawCandidate("紫霄宗", "紫霄宗", ["NN"], None, CAT_FACTION, {"heuristic"}, appearances=1)

    c1_ch3 = RawCandidate("李小明", "李小明", ["NR", "NR", "NR"], "PERSON", CAT_CHARACTER, {"ner"}, appearances=1)

    accumulator: dict[str, RawCandidate] = {}
    merge_across_chapters(accumulator, [c1_ch1, c2_ch1])
    merge_across_chapters(accumulator, [c1_ch2, c3_ch2])
    merge_across_chapters(accumulator, [c1_ch3])

    merged_list = list(accumulator.values())

    # Same as batch merge_candidates
    batch = merge_candidates([c1_ch1, c2_ch1, c1_ch2, c3_ch2, c1_ch3])
    batch_map = {c.normalized_form: c for c in batch}
    assert len(merged_list) == len(batch) == 4

    for c in merged_list:
        bc = batch_map[c.normalized_form]
        assert c.surface_form == bc.surface_form
        assert c.type_prior == bc.type_prior
        assert c.ner_label == bc.ner_label
        assert c.appearances == bc.appearances
        assert c.strategies == bc.strategies

    # Verify type_prior priority: CHARACTER > OTHER
    assert accumulator["李明"].type_prior == CAT_CHARACTER
    assert accumulator["李明"].ner_label == "PERSON"
    assert accumulator["李明"].appearances == 5

    # Verify standalone entry preserved
    assert accumulator["紫霄宗"].type_prior == CAT_FACTION
    assert accumulator["紫霄宗"].appearances == 1

    assert accumulator["李小明"].type_prior == CAT_CHARACTER
    assert accumulator["李小明"].appearances == 1


def test_extract_summary_terms_empty():
    assert extract_summary_terms(None) == []
    assert extract_summary_terms({}) == []


def test_extract_summary_terms_basic():
    result = extract_summary_terms({
        "new_terms": ["青云门", "张三", "紫霄功法"],
        "characters_mentioned": ["张三", "李四"],
        "setting": "青云山",
    })
    terms = {c.surface_form: c for c in result}
    assert len(terms) == 3

    assert terms["青云门"].type_prior == CAT_OTHER
    assert "from_summary" in terms["青云门"].strategies
    assert len(terms["青云门"].pos_tags) == 0

    assert terms["张三"].type_prior == CAT_CHARACTER
    assert "from_summary" in terms["张三"].strategies

    assert terms["紫霄功法"].type_prior == CAT_OTHER


def test_extract_summary_terms_setting_hint():
    result = extract_summary_terms({
        "new_terms": ["青云山", "紫霄洞"],
        "characters_mentioned": ["张三"],
        "setting": "青云山是主角所在的门派",
    })
    terms = {c.surface_form: c for c in result}
    assert terms["青云山"].type_prior == CAT_LOCATION
    # Term appears in setting text → location hint
    assert terms["紫霄洞"].type_prior == CAT_OTHER


def test_extract_summary_terms_character_before_setting():
    """character_mentioned match overrides setting match."""
    result = extract_summary_terms({
        "new_terms": ["青云"],
        "characters_mentioned": ["青云"],
        "setting": "青云山",
    })
    assert result[0].type_prior == CAT_CHARACTER


def test_extract_summary_terms_filters_short():
    result = extract_summary_terms({
        "new_terms": ["门", "青云门", "李"],
        "characters_mentioned": [],
        "setting": "",
    })
    surfaces = {c.surface_form for c in result}
    assert "门" not in surfaces
    assert "李" not in surfaces
    assert "青云门" in surfaces


def test_extract_summary_terms_merge_with_strategies():
    """Summary terms merge correctly with other extraction strategies."""
    summary = extract_summary_terms({
        "new_terms": ["青云门"],
        "characters_mentioned": [],
        "setting": "",
    })
    ner = extract_ner_candidates([
        SegmentedToken(text="青云", pos="NR", ner="ORG", offset_start=0, offset_end=2),
        SegmentedToken(text="门", pos="NR", ner="ORG", offset_start=2, offset_end=3),
    ], "青云门")
    merged = merge_candidates(summary + ner)
    assert len(merged) == 1
    # NER category should override summary's CAT_OTHER
    assert merged[0].type_prior == CAT_FACTION
    assert "from_summary" in merged[0].strategies
    assert "ner" in merged[0].strategies
