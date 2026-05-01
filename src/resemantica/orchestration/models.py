from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


STAGE_ORDER = [
    "preprocess-glossary",
    "preprocess-summaries",
    "preprocess-idioms",
    "preprocess-graph",
    "packets-build",
    "translate-range",
    "epub-rebuild",
]

CALLABLE_STAGES = [*STAGE_ORDER, "translate-chapter", "reset"]


@dataclass
class StageResult:
    success: bool
    stage_name: str
    message: str = ""
    checkpoint: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    stopped: bool = False


def legal_transition(current: Optional[str], target: str) -> bool:
    if current is None:
        return True
    if current == target:
        return True
    try:
        if current not in STAGE_ORDER or target not in CALLABLE_STAGES:
            return False
        if target not in STAGE_ORDER:
            return True
        return STAGE_ORDER.index(target) >= STAGE_ORDER.index(current)
    except ValueError:
        return False


def next_stage(current: Optional[str]) -> Optional[str]:
    if current is None:
        return STAGE_ORDER[0]
    try:
        idx = STAGE_ORDER.index(current)
        if idx + 1 < len(STAGE_ORDER):
            return STAGE_ORDER[idx + 1]
        return None
    except ValueError:
        return None
