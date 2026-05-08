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
    extract_webnovel_dict,
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
