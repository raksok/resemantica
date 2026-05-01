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
    if event.severity == "error":
        return 0
    et = event.event_type.lower()
    for entry in reversed(GRANULARITY_LEVELS):
        for pattern in entry["patterns"]:
            if pattern in et or et.endswith(f".{pattern}") or et == pattern:
                return entry["level"]
    return 1
