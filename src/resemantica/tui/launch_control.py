from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from resemantica.orchestration.models import legal_transition

StageKey = Literal[
    "epub-extract",
    "preprocess-glossary",
    "preprocess-summaries",
    "preprocess-idioms",
    "preprocess-graph",
    "packets-build",
    "translate-range",
    "epub-rebuild",
    "production",
]

STAGE_DEFINITIONS: list[dict[str, Any]] = [
    {"key": "epub-extract", "label": "EPUB Extract", "extraction": True},
    {"key": "preprocess-glossary", "label": "Glossary"},
    {"key": "preprocess-summaries", "label": "Summaries"},
    {"key": "preprocess-idioms", "label": "Idioms"},
    {"key": "preprocess-graph", "label": "Graph"},
    {"key": "packets-build", "label": "Packets"},
    {"key": "translate-range", "label": "Translation"},
    {"key": "epub-rebuild", "label": "Rebuild"},
    {"key": "production", "label": "Full Run"},
]

STAGE_ORDER_KEYS: list[str] = [
    d["key"] for d in STAGE_DEFINITIONS if not d.get("extraction") and d["key"] != "production"
]

_STAGE_PREREQUISITE: dict[str, str | None] = {
    "epub-extract": None,
    "preprocess-glossary": "__extraction__",
    "preprocess-summaries": "preprocess-glossary",
    "preprocess-idioms": "preprocess-summaries",
    "preprocess-graph": "preprocess-idioms",
    "packets-build": "preprocess-graph",
    "translate-range": "packets-build",
    "epub-rebuild": "translate-range",
    "production": "__extraction__",
}


@dataclass
class TuiSession:
    input_path: Path | None = None
    chapter_start: int | None = None
    chapter_end: int | None = None
    latest_result: str | None = None
    latest_failure: str | None = None


@dataclass(frozen=True)
class LaunchContext:
    release_id: str | None
    run_id: str | None
    input_path: Path | None = None
    chapter_start: int | None = None
    chapter_end: int | None = None


@dataclass(frozen=True)
class LaunchAction:
    key: str
    label: str
    enabled: bool
    reason: str
    shortcut: str | None


@dataclass(frozen=True)
class LaunchStageStatus:
    key: str
    label: str
    status: str
    action: LaunchAction
    latest_event: str | None
    latest_failure: str | None


@dataclass(frozen=True)
class LaunchSnapshot:
    context: LaunchContext
    active_action: str | None
    stages: list[LaunchStageStatus]
    latest_failure: str | None


def is_stale(
    timestamp_str: str | None,
    *,
    now: datetime | None = None,
    timeout_seconds: int = 300,
) -> bool:
    if not timestamp_str:
        return False
    try:
        parsed = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return (current - parsed).total_seconds() >= timeout_seconds


def _stage_shortcut(key: str) -> str | None:
    return {
        "epub-extract": "e",
        "preprocess-glossary": "g",
        "preprocess-summaries": "s",
        "preprocess-idioms": "i",
        "preprocess-graph": "r",
        "packets-build": "b",
        "translate-range": "t",
        "epub-rebuild": "u",
        "production": "p",
    }.get(key)


def _completed_stages_from_events(events: list) -> set[str]:
    completed: set[str] = set()
    for event in events:
        if getattr(event, "event_type", None) == "stage_completed":
            completed.add(getattr(event, "stage_name", ""))
    return completed


def _failed_stages_from_events(events: list) -> dict[str, str]:
    failed: dict[str, str] = {}
    for event in events:
        if getattr(event, "event_type", None) == "stage_failed":
            failed[getattr(event, "stage_name", "")] = str(
                getattr(event, "message", "") or "Unknown failure"
            )
    return failed


def build_snapshot(
    context: LaunchContext,
    active_action: str | None,
    run_state: dict | None,
    events: list,
    extraction_manifest_exists: bool,
) -> LaunchSnapshot:
    completed = _completed_stages_from_events(events)
    failed = _failed_stages_from_events(events)

    current_stage = run_state["stage_name"] if run_state else None
    current_status = run_state["status"] if run_state else None
    current_started = run_state["started_at"] if run_state else None

    stages: list[LaunchStageStatus] = []
    overall_failure: str | None = None

    for definition in STAGE_DEFINITIONS:
        key = definition["key"]
        label = definition["label"]
        is_extraction = definition.get("extraction", False)

        status: str
        reason: str = ""
        stage_failure: str | None = None

        if active_action == key:
            status = "running"
        elif key in failed:
            status = "failed"
            stage_failure = failed[key]
        elif key in completed:
            status = "done"
        elif is_extraction:
            status = _extraction_readiness(
                context=context,
                active_action=active_action,
                extraction_manifest_exists=extraction_manifest_exists,
            )
            _, reason = status, _extraction_reason(context, extraction_manifest_exists)
        elif key == "production":
            status = _production_readiness(
                context=context,
                active_action=active_action,
                completed=completed,
                extraction_manifest_exists=extraction_manifest_exists,
                current_stage=current_stage,
                current_status=current_status,
            )
            reason = _production_reason(
                context, extraction_manifest_exists, completed, active_action
            )
        else:
            status = _stage_readiness(
                key=key,
                context=context,
                active_action=active_action,
                completed=completed,
                extraction_manifest_exists=extraction_manifest_exists,
                current_stage=current_stage,
            )
            reason = _stage_reason(
                key, context, extraction_manifest_exists, completed, active_action
            )

        if (
            current_stage == key
            and current_status == "running"
            and status not in ("running", "done", "failed")
        ):
            if is_stale(current_started):
                status = "stale"
            else:
                status = "running"

        if stage_failure and overall_failure is None:
            overall_failure = stage_failure

        action = LaunchAction(
            key=key,
            label=label,
            enabled=(status == "ready"),
            reason=reason,
            shortcut=_stage_shortcut(key),
        )

        stages.append(
            LaunchStageStatus(
                key=key,
                label=label,
                status=status,
                action=action,
                latest_event=None,
                latest_failure=stage_failure,
            )
        )

    return LaunchSnapshot(
        context=context,
        active_action=active_action,
        stages=stages,
        latest_failure=overall_failure,
    )


def _extraction_readiness(
    context: LaunchContext,
    active_action: str | None,
    extraction_manifest_exists: bool,
) -> str:
    if context.input_path is None:
        return "missing"
    if active_action is not None:
        return "blocked"
    return "ready"


def _extraction_reason(context: LaunchContext, extraction_manifest_exists: bool) -> str:
    if context.input_path is None:
        return "No EPUB path selected"
    if extraction_manifest_exists:
        return "Already extracted"
    return ""


def _production_readiness(
    context: LaunchContext,
    active_action: str | None,
    completed: set[str],
    extraction_manifest_exists: bool,
    current_stage: str | None,
    current_status: str | None,
) -> str:
    if current_stage and current_status == "running":
        return "running"
    if active_action is not None:
        return "blocked"
    if context.release_id is None:
        return "disabled"
    if context.run_id is None:
        return "disabled"
    if not extraction_manifest_exists:
        return "missing"
    if all(s in completed for s in STAGE_ORDER_KEYS):
        return "done"
    return "ready"


def _production_reason(
    context: LaunchContext,
    extraction_manifest_exists: bool,
    completed: set[str],
    active_action: str | None,
) -> str:
    if context.release_id is None:
        return "No release ID set"
    if context.run_id is None:
        return "No run ID set"
    if not extraction_manifest_exists:
        return "Extraction required first"
    if active_action is not None:
        return "Another action is running"
    if all(s in completed for s in STAGE_ORDER_KEYS):
        return "All stages complete"
    return ""


def _stage_readiness(
    key: str,
    context: LaunchContext,
    active_action: str | None,
    completed: set[str],
    extraction_manifest_exists: bool,
    current_stage: str | None,
) -> str:
    if active_action is not None:
        return "blocked"
    if context.release_id is None:
        return "disabled"
    if context.run_id is None:
        return "disabled"

    prereq = _STAGE_PREREQUISITE.get(key)
    if prereq == "__extraction__":
        if not extraction_manifest_exists:
            return "missing"
    elif prereq is not None:
        if prereq not in completed:
            return "blocked"

    if not legal_transition(current_stage, key):
        return "blocked"

    return "ready"


def _stage_reason(
    key: str,
    context: LaunchContext,
    extraction_manifest_exists: bool,
    completed: set[str],
    active_action: str | None,
) -> str:
    if active_action is not None:
        return "Another action is running"
    if context.release_id is None:
        return "No release ID set"
    if context.run_id is None:
        return "No run ID set"

    prereq = _STAGE_PREREQUISITE.get(key)
    if prereq == "__extraction__":
        if not extraction_manifest_exists:
            return "Extraction required first"
    elif prereq is not None:
        if prereq not in completed:
            return f"'{prereq}' must complete first"

    return ""


def next_available_stage(snapshot: LaunchSnapshot) -> LaunchStageStatus | None:
    for stage in snapshot.stages:
        if stage.action.enabled:
            return stage
    return None
