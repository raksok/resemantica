from __future__ import annotations

from typing import Any

from resemantica.tracking.models import Event

GRANULARITY_LEVELS: list[dict[str, Any]] = [
    {"level": 0, "name": "ERROR", "patterns": []},
    {
        "level": 1,
        "name": "STAGE",
        "patterns": [
            "started",
            "completed",
            "failed",
            "transition_denied",
            "finalized",
        ],
    },
    {
        "level": 2,
        "name": "CHAPTER",
        "patterns": [
            "chapter_started",
            "chapter_completed",
            "chapter_skipped",
        ],
    },
    {
        "level": 3,
        "name": "PARAGRAPH",
        "patterns": [
            "paragraph_started",
            "paragraph_completed",
            "paragraph_skipped",
        ],
    },
    {
        "level": 4,
        "name": "TOKEN",
        "patterns": [
            "retry",
            "risk_detected",
            "term_found",
            "entity_extracted",
            "draft_generated",
            "validation_",
        ],
    },
]


def classify_event_level(event: Event) -> int:
    return classify_signal_level(event.event_type, severity=event.severity)


def classify_signal_level(event_type: str, *, severity: str = "info") -> int:
    if severity == "error":
        return 0
    if severity == "debug":
        return 4
    et = event_type.lower()
    for entry in reversed(GRANULARITY_LEVELS):
        for pattern in entry["patterns"]:
            if pattern in et or et.endswith(f".{pattern}") or et == pattern:
                return entry["level"]
    return 1


def cli_verbosity_to_level(verbosity: int) -> int:
    return min(max(int(verbosity), 0), 4)


def tui_verbosity_to_level(verbosity: str) -> int:
    return {
        "normal": 2,
        "verbose": 3,
        "debug": 4,
    }.get(verbosity, 4)
