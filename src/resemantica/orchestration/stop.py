from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any


class StopRequested(Exception):
    def __init__(
        self,
        message: str = "Stop requested; stopped after current unit",
        *,
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.checkpoint = checkpoint or {}


@dataclass(slots=True)
class StopToken:
    _event: Event = field(default_factory=Event)

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
