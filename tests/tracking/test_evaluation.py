from __future__ import annotations

import json
from pathlib import Path

from resemantica.tracking.evaluation import (
    run_benchmark,
    score_fidelity,
    score_readability,
    score_terminology,
)


def _fake_translate(text: str) -> str:
    table = {
        "在下只是一介散修，岂敢与前辈相提并论。":
            "I am but a wandering cultivator, how would I dare to compare myself with you, Senior.",
        "画龙画虎难画骨，知人知面不知心。":
            "Dragons and tigers are easy to draw, but bones are hard; a man's face and appearance are easy to know, but his heart is not.",
    }
    return table.get(text, f"translated: {text}")


class TestScoreFidelity:
    def test_exact_match(self):
        assert score_fidelity("hello world", "hello world") == 1.0

    def test_partial_match(self):
        score = score_fidelity("hello world", "hello there")
        assert 0.0 < score < 1.0

    def test_no_match(self):
        assert score_fidelity("abc", "xyz") == 0.0

    def test_empty_strings(self):
        assert score_fidelity("", "") == 0.0
        assert score_fidelity("", "hello") == 0.0
        assert score_fidelity("hello", "") == 0.0


class TestScoreTerminology:
    def test_all_terms_present(self):
        assert score_terminology("The quick brown fox", ["quick", "fox"]) == 1.0

    def test_some_terms_missing(self):
        score = score_terminology("The quick brown fox", ["quick", "rabbit"])
        assert score == 0.5

    def test_no_terms(self):
        assert score_terminology("hello world", []) == 1.0

    def test_empty_text(self):
        assert score_terminology("", ["hello"]) == 0.0

    def test_case_insensitive(self):
        assert score_terminology("Hello World", ["hello", "world"]) == 1.0


class TestScoreReadability:
    def test_readable_text(self):
        score = score_readability("The cat sat on the mat. It was a sunny day.")
        assert 0.0 <= score <= 1.0

    def test_empty_text(self):
        assert score_readability("") == 0.0

    def test_returns_float(self):
        score = score_readability("Hello world.")
        assert isinstance(score, float)


class TestRunBenchmark:
    def test_returns_expected_keys(self, tmp_path: Path):
        items = [
            {
                "source_zh": "在下只是一介散修，岂敢与前辈相提并论。",
                "expected_en": "I am but a wandering cultivator, how would I dare to compare myself with you, Senior.",
                "category": "honorific",
                "difficulty": 2,
            }
        ]
        golden_path = tmp_path / "golden.json"
        with open(golden_path, "w", encoding="utf-8") as f:
            json.dump(items, f)

        result = run_benchmark(golden_path, _fake_translate)

        assert "total_items" in result
        assert "avg_fidelity" in result
        assert "avg_readability" in result
        assert "results" in result
        assert result["total_items"] == 1

    def test_multiple_items_aggregates(self, tmp_path: Path):
        items = [
            {
                "source_zh": "在下只是一介散修，岂敢与前辈相提并论。",
                "expected_en": "I am but a wandering cultivator, how would I dare to compare myself with you, Senior.",
                "category": "honorific",
                "difficulty": 2,
            },
            {
                "source_zh": "画龙画虎难画骨，知人知面不知心。",
                "expected_en": "Dragons and tigers are easy to draw, but bones are hard; a man's face and appearance are easy to know, but his heart is not.",
                "category": "idiom",
                "difficulty": 3,
            },
        ]
        golden_path = tmp_path / "golden.json"
        with open(golden_path, "w", encoding="utf-8") as f:
            json.dump(items, f)

        result = run_benchmark(golden_path, _fake_translate)

        assert result["total_items"] == 2
        assert 0.0 <= result["avg_fidelity"] <= 1.0
        assert 0.0 <= result["avg_readability"] <= 1.0
        assert len(result["results"]) == 2

    def test_terminology_scoring(self, tmp_path: Path):
        items = [
            {
                "source_zh": "测试文本",
                "expected_en": "test text",
                "category": "test",
                "difficulty": 1,
            }
        ]
        golden_path = tmp_path / "golden.json"
        with open(golden_path, "w", encoding="utf-8") as f:
            json.dump(items, f)

        def translate(s: str) -> str:
            return "test text with consistent terms"

        result = run_benchmark(golden_path, translate, terms=["test", "text"])
        assert result["results"][0]["scores"]["terminology"] == 1.0

    def test_golden_set_fixture_loads(self):
        fixture_path = Path(__file__).parent.parent / "golden_set" / "paragraphs.json"
        assert fixture_path.exists()
        with open(fixture_path, encoding="utf-8") as f:
            items = json.load(f)
        assert len(items) >= 5

        categories = {item["category"] for item in items}
        for expected in ("honorific", "idiom", "lore_exposition", "pronoun_ambiguity"):
            assert expected in categories
