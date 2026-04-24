from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional


def _load_golden_set(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def score_fidelity(translated: str, expected: str) -> float:
    if not translated or not expected:
        return 0.0
    return round(SequenceMatcher(None, translated, expected).ratio(), 4)


def score_terminology(translated: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    if not translated:
        return 0.0
    t_lower = translated.lower()
    matches = sum(1 for t in terms if t.lower() in t_lower)
    return round(matches / len(terms), 4)


def score_readability(text: str) -> float:
    if not text:
        return 0.0
    words = [w for w in text.split() if w]
    if not words:
        return 0.0
    avg_word_len = sum(len(w) for w in words) / len(words)

    sentences = [
        s.strip()
        for s in text.replace("!", ".").replace("?", ".").split(".")
        if s.strip()
    ]
    avg_sentence_len = len(words) / max(len(sentences), 1)

    word_score = max(0.0, 1.0 - abs(avg_word_len - 5.0) / 5.0)
    sentence_score = max(0.0, 1.0 - abs(avg_sentence_len - 17.0) / 17.0)
    return round((word_score + sentence_score) / 2, 4)


def run_benchmark(
    golden_set_path: Path,
    translate_fn,
    *,
    terms: Optional[list[str]] = None,
) -> dict[str, Any]:
    items = _load_golden_set(golden_set_path)
    results: list[dict[str, Any]] = []
    total_fidelity = 0.0
    total_readability = 0.0

    for item in items:
        source = item["source_zh"]
        expected = item["expected_en"]
        category = item.get("category", "unknown")
        difficulty = item.get("difficulty", 1)

        translated = translate_fn(source)

        fidelity = score_fidelity(translated, expected)
        readability = score_readability(translated)
        terminology = score_terminology(translated, terms or [])

        total_fidelity += fidelity
        total_readability += readability

        results.append(
            {
                "source": source,
                "expected": expected,
                "translated": translated,
                "category": category,
                "difficulty": difficulty,
                "scores": {
                    "fidelity": fidelity,
                    "readability": readability,
                    "terminology": terminology,
                },
            }
        )

    n = len(results)
    return {
        "total_items": n,
        "avg_fidelity": round(total_fidelity / n, 4) if n else 0.0,
        "avg_readability": round(total_readability / n, 4) if n else 0.0,
        "results": results,
    }
