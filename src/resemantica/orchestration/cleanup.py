from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from .events import emit_event
from resemantica.settings import load_config


def _get_cleanup_plan_path(release_id: str) -> Path:
    cfg = load_config()
    return Path(cfg.paths.artifact_root) / release_id / "cleanup_plan.json"


def plan_cleanup(
    release_id: str,
    run_id: str,
    *,
    scope: str = "run",
    dry_run: bool = True,
) -> dict[str, Any]:
    plan_path = _get_cleanup_plan_path(release_id)

    plan: dict[str, Any] = {
        "release_id": release_id,
        "run_id": run_id,
        "scope": scope,
        "dry_run": dry_run,
        "deletable_artifacts": [],
        "preserved_artifacts": [],
        "sqlite_rows": [],
        "estimated_space_bytes": 0,
    }

    cfg = load_config()
    artifacts_dir = Path(cfg.paths.artifact_root) / release_id

    if scope in ("run", "translation", "preprocess", "cache", "all"):
        if artifacts_dir.exists():
            for p in artifacts_dir.rglob("*"):
                if p.is_file():
                    rel = str(p.relative_to(artifacts_dir))
                    plan["deletable_artifacts"].append(rel)
                    try:
                        plan["estimated_space_bytes"] += p.stat().st_size
                    except OSError:
                        pass

    plan_path.parent.mkdir(parents=True, exist_ok=True)
    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=2)

    emit_event(
        run_id, release_id, "cleanup.plan_created",
        "cleanup", message=f"Cleanup plan created: {plan_path}",
        payload={"scope": scope, "dry_run": dry_run, "plan_path": str(plan_path)}
    )

    return plan


def apply_cleanup(
    release_id: str,
    run_id: str,
    *,
    scope: str = "run",
    force: bool = False,
) -> dict[str, Any]:
    plan_path = _get_cleanup_plan_path(release_id)

    if not plan_path.exists():
        msg = "No cleanup plan found. Run cleanup-plan first."
        emit_event(
            run_id, release_id, "cleanup.apply_failed",
            "cleanup", severity="error", message=msg
        )
        return {"success": False, "message": msg}

    with open(plan_path) as f:
        plan = json.load(f)

    if not force and plan.get("scope") != scope:
        msg = f"Plan scope {plan.get('scope')} does not match requested scope {scope}"
        emit_event(
            run_id, release_id, "cleanup.apply_failed",
            "cleanup", severity="error", message=msg
        )
        return {"success": False, "message": msg}

    report: dict[str, Any] = {
        "release_id": release_id,
        "run_id": run_id,
        "scope": scope,
        "deleted_files": [],
        "errors": [],
    }

    cfg = load_config()
    artifacts_dir = Path(cfg.paths.artifact_root) / release_id

    for rel in plan.get("deletable_artifacts", []):
        target = artifacts_dir / rel
        if target.exists():
            try:
                target.unlink()
                report["deleted_files"].append(rel)
            except Exception as exc:
                report["errors"].append(str(exc))

    emit_event(
        run_id, release_id, "cleanup.apply_completed",
        "cleanup",
        message=f"Cleanup applied: {len(report['deleted_files'])} files deleted",
        payload=report
    )

    return report
