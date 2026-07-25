from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any


@dataclass(frozen=True, slots=True)
class InterruptReport:
    stage: str
    phase: str
    unit_kind: str
    completed_count: int
    drained_count: int
    canceled_count: int
    last_durable_unit: str | None = None
    next_resumable_unit: str | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)
    llm_usage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "phase": self.phase,
            "unit_kind": self.unit_kind,
            "completed_count": self.completed_count,
            "drained_count": self.drained_count,
            "canceled_count": self.canceled_count,
            "last_durable_unit": self.last_durable_unit,
            "next_resumable_unit": self.next_resumable_unit,
            "checkpoint": dict(self.checkpoint),
            "llm_usage": dict(self.llm_usage),
        }


class StopRequested(Exception):
    def __init__(
        self,
        message: str = "Stop requested; stopped after current unit",
        *,
        checkpoint: dict[str, Any] | None = None,
        interrupt_report: InterruptReport | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.checkpoint = checkpoint or {}
        self.interrupt_report = interrupt_report


@dataclass(slots=True)
class StopToken:
    _event: Event = field(default_factory=Event)
    force: bool = False

    def request_stop(self) -> None:
        self._event.set()

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    def raise_if_requested(
        self,
        *,
        checkpoint: dict[str, Any] | None = None,
        message: str = "Stop requested; stopped after current unit",
    ) -> None:
        if self.requested:
            raise StopRequested(message, checkpoint=checkpoint)


def raise_if_stop_requested(
    stop_token: StopToken | None,
    *,
    checkpoint: dict[str, Any] | None = None,
    message: str = "Stop requested; stopped after current unit",
) -> None:
    if stop_token is not None:
        stop_token.raise_if_requested(checkpoint=checkpoint, message=message)
