from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


STAGE_ORDER = [
    "preprocess-glossary",
    "preprocess-summaries",
    "preprocess-idioms",
    "preprocess-graph",
    "packets-build",
    "translate-chapter",
    "translate-pass3",
    "epub-rebuild",
]


@dataclass
class StageResult:
    success: bool
    stage_name: str
    message: str = ""
    checkpoint: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


def legal_transition(current: Optional[str], target: str) -> bool:
    if current is None:
        return True
    if current == target:
        return True
    try:
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
