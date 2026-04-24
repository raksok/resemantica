from __future__ import annotations

from typing import Any

from resemantica.tracking.repo import ensure_tracking_db


def get_stage_summary(release_id: str) -> list[dict[str, Any]]:
    conn = ensure_tracking_db(release_id)
    try:
        rows = conn.execute(
            """
            SELECT stage_name, event_type, COUNT(*) as cnt
            FROM events
            WHERE event_type IN ('stage.completed', 'stage.failed', 'stage.error')
            GROUP BY stage_name, event_type
            ORDER BY stage_name
            """
        ).fetchall()
        summary: dict[str, dict[str, int]] = {}
        for row in rows:
            stage = row["stage_name"]
            if stage not in summary:
                summary[stage] = {"stage": stage, "completed": 0, "failed": 0, "errors": 0}
            key = {"stage.completed": "completed", "stage.failed": "failed", "stage.error": "errors"}.get(
                row["event_type"], "completed"
            )
            summary[stage][key] = row["cnt"]
        return list(summary.values())
    finally:
        conn.close()


def get_warning_trends(release_id: str, limit: int = 10) -> list[dict[str, Any]]:
    conn = ensure_tracking_db(release_id)
    try:
        rows = conn.execute(
            """
            SELECT severity, event_type, message, event_time, stage_name
            FROM events
            WHERE severity IN ('warning', 'error')
            ORDER BY event_time DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "severity": r["severity"],
                "event_type": r["event_type"],
                "message": r["message"],
                "event_time": r["event_time"],
                "stage_name": r["stage_name"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_metric_totals(release_id: str) -> dict[str, int]:
    conn = ensure_tracking_db(release_id)
    try:
        total_events = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()["c"]
        warnings = conn.execute(
            "SELECT COUNT(*) as c FROM events WHERE severity = 'warning'"
        ).fetchone()["c"]
        errors = conn.execute(
            "SELECT COUNT(*) as c FROM events WHERE severity = 'error'"
        ).fetchone()["c"]
        stages_run = conn.execute(
            "SELECT COUNT(DISTINCT stage_name) as c FROM events WHERE event_type LIKE 'stage.%'"
        ).fetchone()["c"]
        return {
            "total_events": total_events,
            "warnings": warnings,
            "errors": errors,
            "stages_run": stages_run,
        }
    finally:
        conn.close()
