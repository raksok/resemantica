from __future__ import annotations

from typing import Optional

from resemantica.tracking.repo import ensure_tracking_db, load_run_state

from .events import emit_event
from .models import STAGE_ORDER, StageResult, next_stage
from .runner import run_stage


def resume_run(
    release_id: str,
    run_id: str,
    *,
    from_stage: Optional[str] = None,
) -> StageResult:
    conn = ensure_tracking_db(release_id)
    try:
        state = load_run_state(conn, run_id)
    finally:
        conn.close()

    if state is None:
        msg = f"No checkpoint found for run {run_id}"
        emit_event(
            run_id, release_id, "resume.failed",
            "unknown", severity="error", message=msg
        )
        return StageResult(success=False, stage_name="unknown", message=msg)

    if from_stage is not None:
        start_stage = from_stage
    else:
        start_stage = state.stage_name

    if start_stage not in STAGE_ORDER:
        msg = f"Invalid stage for resume: {start_stage}"
        emit_event(
            run_id, release_id, "resume.failed",
            start_stage, severity="error", message=msg
        )
        return StageResult(success=False, stage_name=start_stage, message=msg)

    emit_event(
        run_id, release_id, "resume.started",
        start_stage,
        message=f"Resuming from stage {start_stage}",
        payload={"checkpoint": state.checkpoint},
    )

    current: str = start_stage
    while current is not None:
        result = run_stage(
            release_id, run_id, current,
            checkpoint=state.checkpoint if current == start_stage else None
        )
        if not result.success:
            emit_event(
                run_id, release_id, "resume.failed",
                current, severity="error",
                message=f"Resume failed at stage {current}: {result.message}"
            )
            return result
        next_val = next_stage(current)
        if next_val is None:
            break
        current = next_val

    emit_event(
        run_id, release_id, "resume.completed",
        "all",
        message="Resume completed successfully"
    )
    return StageResult(
        success=True, stage_name="all",
        message="Resume completed successfully"
    )
