from __future__ import annotations

from datetime import datetime, timezone

from resemantica.tracking.models import Event


def _make_event(
    *,
    event_type: str,
    severity: str = "info",
    stage_name: str = "test-stage",
    chapter_number: int | None = None,
) -> Event:
    return Event(
        event_type=event_type,
        event_time=datetime.now(timezone.utc).isoformat(),
        run_id="run-1",
        release_id="rel-1",
        stage_name=stage_name,
        severity=severity,
        chapter_number=chapter_number,
    )
