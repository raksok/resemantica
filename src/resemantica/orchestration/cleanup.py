from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from resemantica.settings import derive_paths, load_config

from .events import emit_event


def _get_cleanup_plan_path(release_id: str, *, scope: str = "run") -> Path:
    cfg = load_config()
    if scope == "factory":
        return Path(cfg.paths.artifact_root) / "factory_cleanup_plan.json"
    return derive_paths(cfg, release_id=release_id).release_root / "cleanup_plan.json"


def _get_cleanup_report_path(release_id: str, *, scope: str = "run") -> Path:
    cfg = load_config()
    if scope == "factory":
        return Path(cfg.paths.artifact_root) / "factory_cleanup_report.json"
    return derive_paths(cfg, release_id=release_id).release_root / "cleanup_report.json"


def _collect_scope_artifacts(
    release_id: str, run_id: str, scope: str
) -> tuple[list[Path], list[Path]]:
    cfg = load_config()
    deletable: list[Path] = []
    preserved: list[Path] = []

    if scope == "factory":
        artifact_root = Path(cfg.paths.artifact_root)
        releases_dir = artifact_root / "releases"
        if releases_dir.exists():
            deletable.append(releases_dir)
        global_db = artifact_root / cfg.paths.db_filename
        if global_db.exists():
            deletable.append(global_db)
        return deletable, preserved

    release_root = derive_paths(cfg, release_id=release_id).release_root

    if not release_root.exists():
        return deletable, preserved

    if scope == "run":
        run_dir = release_root / "runs" / run_id
        if run_dir.exists():
            deletable.append(run_dir)

    elif scope == "translation":
        run_dir = release_root / "runs" / run_id
        translation_dir = run_dir / "translation"
        if translation_dir.exists():
            deletable.append(translation_dir)

    elif scope == "preprocess":
        for subdir in ["extracted", "glossary", "summaries", "idioms", "graph", "packets"]:
            target = release_root / subdir
            if target.exists():
                deletable.append(target)

    elif scope == "cache":
        cache_dir = release_root / ".cache"
        if cache_dir.exists():
            deletable.append(cache_dir)

    elif scope == "all":
        for p in release_root.iterdir():
            if p.name in ("tracking.db", "cleanup_plan.json", "cleanup_report.json"):
                preserved.append(p)
            else:
                deletable.append(p)

    return deletable, preserved


def _estimate_size(paths: list[Path]) -> int:
    total = 0
    for p in paths:
        if p.exists():
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    total = -1
            elif p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file():
                        try:
                            total += f.stat().st_size
                        except OSError:
                            total = -1
    return total


def plan_cleanup(
    release_id: str,
    run_id: str,
    *,
    scope: str = "run",
    dry_run: bool = True,
) -> dict[str, object]:
    plan_path = _get_cleanup_plan_path(release_id, scope=scope)

    deletable, preserved = _collect_scope_artifacts(release_id, run_id, scope)

    if scope == "factory":
        sqlite_rows: list[dict[str, str]] = []
    else:
        sqlite_rows = [
            {"database": "tracking.db", "table": "events", "run_id": run_id},
            {"database": "tracking.db", "table": "run_state", "run_id": run_id},
            {"database": "resemantica.db", "table": "translation_checkpoints", "run_id": run_id},
            {"database": "resemantica.db", "table": "extracted_chapters", "run_id": run_id},
            {"database": "resemantica.db", "table": "extracted_blocks", "run_id": run_id},
        ]

    plan: dict[str, object] = {
        "release_id": release_id,
        "run_id": run_id,
        "scope": scope,
        "dry_run": dry_run,
        "deletable_artifacts": [str(p) for p in deletable],
        "preserved_artifacts": [str(p) for p in preserved],
        "sqlite_rows": sqlite_rows,
        "estimated_space_bytes": _estimate_size(deletable),
        "schema_version": "1.0",
    }

    plan_path.parent.mkdir(parents=True, exist_ok=True)
    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=2, default=str)

    emit_event(
        run_id or "__factory__", release_id or "__factory__", "cleanup.plan_created",
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
) -> dict[str, object]:
    plan_path = _get_cleanup_plan_path(release_id, scope=scope)

    if not plan_path.exists():
        msg = "No cleanup plan found. Run cleanup-plan first."
        emit_event(
            run_id or "__factory__", release_id or "__factory__", "cleanup.apply_failed",
            "cleanup", severity="error", message=msg
        )
        return {"success": False, "message": msg}

    with open(plan_path) as f:
        plan = json.load(f)

    if not force and plan.get("scope") != scope:
        msg = f"Plan scope {plan.get('scope')} does not match requested scope {scope}"
        emit_event(
            run_id or "__factory__", release_id or "__factory__", "cleanup.apply_failed",
            "cleanup", severity="error", message=msg
        )
        return {"success": False, "message": msg}

    report: dict[str, Any] = {
        "release_id": release_id,
        "run_id": run_id,
        "scope": scope,
        "deleted_files": [],
        "deleted_dirs": [],
        "sqlite_rows_deleted": 0,
        "errors": [],
    }

    for artifact_str in plan.get("deletable_artifacts", []):
        target = Path(artifact_str)
        if target.exists():
            try:
                if target.is_file():
                    target.unlink()
                    report["deleted_files"].append(artifact_str)
                elif target.is_dir():
                    shutil.rmtree(target)
                    report["deleted_dirs"].append(artifact_str)
            except Exception as exc:
                report["errors"].append(str(exc))

    if scope == "factory":
        pass
    else:
        from resemantica.db.sqlite import open_connection
        from resemantica.tracking.repo import ensure_tracking_db
        try:
            conn = ensure_tracking_db(release_id)
            try:
                for table in ("events", "run_state"):
                    cursor = conn.execute(
                        f"DELETE FROM {table} WHERE release_id = ? AND run_id = ?",
                        (release_id, run_id),
                    )
                    report["sqlite_rows_deleted"] += max(cursor.rowcount, 0)
                    conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            report["errors"].append(f"Tracking SQLite cleanup error: {exc}")

        try:
            cfg = load_config()
            paths = derive_paths(cfg, release_id=release_id)
            conn = open_connection(paths.db_path)
            try:
                for table in ("translation_checkpoints", "extracted_chapters", "extracted_blocks"):
                    exists = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()
                    if not exists:
                        continue
                    cursor = conn.execute(
                        f"DELETE FROM {table} WHERE release_id = ? AND run_id = ?",
                        (release_id, run_id),
                    )
                    report["sqlite_rows_deleted"] += max(cursor.rowcount, 0)
                    conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            report["errors"].append(f"Global SQLite cleanup error: {exc}")

    report_path = _get_cleanup_report_path(release_id, scope=scope)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    emit_event(
        run_id or "__factory__", release_id or "__factory__", "cleanup.apply_completed",
        "cleanup",
        message=f"Cleanup applied: {len(report['deleted_files'])} files, {len(report['deleted_dirs'])} dirs deleted",
        payload=report
    )

    return report
