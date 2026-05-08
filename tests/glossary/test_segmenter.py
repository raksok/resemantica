from __future__ import annotations

from resemantica.glossary.segmenter import _fallback_segment, segment_chapter


def test_fallback_segment():
    text = "Hello 世界！"
    tokens = _fallback_segment(text)
    assert len(tokens) == 4

    # "Hello"
    assert tokens[0].text == "Hello"
    assert tokens[0].pos == "FW"
    assert tokens[0].offset_start == 0
    assert tokens[0].offset_end == 5

    # "世"
    assert tokens[1].text == "世"
    assert tokens[1].pos == ""
    assert tokens[1].offset_start == 6
    assert tokens[1].offset_end == 7

    # "界"
    assert tokens[2].text == "界"
    assert tokens[2].pos == ""
    assert tokens[2].offset_start == 7
    assert tokens[2].offset_end == 8

    # "！"
    assert tokens[3].text == "！"
    assert tokens[3].pos == ""
    assert tokens[3].offset_start == 8
    assert tokens[3].offset_end == 9


def test_segment_chapter_fallback(monkeypatch):
    monkeypatch.setattr("resemantica.glossary.segmenter._load_hanlp_pipeline", lambda: None)
    text = "修仙界"
    tokens = segment_chapter(text)
    assert len(tokens) == 3
    assert tokens[0].text == "修"
    assert tokens[1].text == "仙"
    assert tokens[2].text == "界"


def test_segment_chapter_with_hanlp_mock(monkeypatch):
    # Mock pipeline returns a dictionary
    def mock_pipeline(line: str) -> dict[str, list]:
        if line.strip() == "修仙界":
            return {
                "tok/fine": ["修仙", "界"],
                "pos/ctb": ["NN", "NN"],
                "ner/msra": [["修仙", "LOC", 0, 1]], # entity '修仙', label 'LOC', starts at tok 0, ends at tok 1
            }
        elif line.strip() == "李明去北京":
            return {
                "tok/fine": ["李明", "去", "北京"],
                "pos/ctb": ["NR", "VV", "NR"],
                "ner/msra": [["李明", "PERSON", 0, 1], ["北京", "LOC", 2, 3]],
            }
        return {"tok/fine": list(line.strip()), "pos/ctb": [""] * len(line.strip())}

    monkeypatch.setattr("resemantica.glossary.segmenter._load_hanlp_pipeline", lambda: mock_pipeline)

    text = "李明去北京\n修仙界"
    tokens = segment_chapter(text)

    # The string is "李明去北京\n修仙界"
    # Line 1: "李明去北京\n" -> tok "李明", "去", "北京"
    assert len(tokens) == 5

    assert tokens[0].text == "李明"
    assert tokens[0].pos == "NR"
    assert tokens[0].ner == "PERSON"
    assert tokens[0].offset_start == 0
    assert tokens[0].offset_end == 2

    assert tokens[1].text == "去"
    assert tokens[1].pos == "VV"
    assert tokens[1].ner is None
    assert tokens[1].offset_start == 2
    assert tokens[1].offset_end == 3

    assert tokens[2].text == "北京"
    assert tokens[2].pos == "NR"
    assert tokens[2].ner == "LOC"
    assert tokens[2].offset_start == 3
    assert tokens[2].offset_end == 5

    # Line 2: "修仙界"
    assert tokens[3].text == "修仙"
    assert tokens[3].pos == "NN"
    assert tokens[3].ner == "LOC"
    assert tokens[3].offset_start == 6
    assert tokens[3].offset_end == 8

    assert tokens[4].text == "界"
    assert tokens[4].pos == "NN"
    assert tokens[4].ner is None
    assert tokens[4].offset_start == 8
    assert tokens[4].offset_end == 9
