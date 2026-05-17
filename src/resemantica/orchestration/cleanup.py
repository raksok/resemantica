from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from resemantica.settings import derive_paths, load_config

from .events import emit_event

CLEANUP_SCOPES = ("run", "translation", "preprocess", "cache", "keep-extracted", "all", "factory")
CleanupScope = Literal["run", "translation", "preprocess", "cache", "keep-extracted", "all", "factory"]
SUPPORTED_CLEANUP_PLAN_SCHEMA = "1.1"

_PROTECTED_RELEASE_ARTIFACTS = {
    "tracking.db",
    "resemantica.db",
    "graph.ladybug",
    "cleanup_plan.json",
    "cleanup_report.json",
}


def _sqlite_target(
    database: str,
    table: str,
    column: str,
    *,
    release_column: str | None = "release_id",
) -> dict[str, Any]:
    return {
        "database": database,
        "table": table,
        "column": column,
        "release_column": release_column,
    }


_TRACKING_SQLITE_TARGETS = (
    _sqlite_target("tracking.db", "events", "run_id"),
    _sqlite_target("tracking.db", "run_state", "run_id"),
)

_RELEASE_SQLITE_TARGETS = {
    "translation": (
        _sqlite_target("resemantica.db", "translation_checkpoints", "run_id"),
    ),
    "extraction": (
        _sqlite_target("resemantica.db", "extracted_blocks", "run_id"),
        _sqlite_target("resemantica.db", "extracted_chapters", "run_id"),
    ),
    "preprocess_downstream": (
        _sqlite_target("resemantica.db", "summary_checkpoints", "run_id"),
        _sqlite_target("resemantica.db", "summary_drafts", "run_id"),
        _sqlite_target("resemantica.db", "validated_summaries_zh", "run_id"),
        _sqlite_target("resemantica.db", "derived_summaries_en", "run_id"),
        _sqlite_target("resemantica.db", "glossary_checkpoints", "run_id"),
        _sqlite_target("resemantica.db", "glossary_translation_votes", "translation_run_id"),
        _sqlite_target("resemantica.db", "glossary_alias_clusters", "discovery_run_id"),
        _sqlite_target("resemantica.db", "glossary_candidates", "discovery_run_id"),
        _sqlite_target("resemantica.db", "idiom_checkpoints", "run_id"),
        _sqlite_target("resemantica.db", "idiom_translation_votes", "translation_run_id"),
        _sqlite_target("resemantica.db", "idiom_candidates", "detection_run_id"),
        _sqlite_target("resemantica.db", "graph_extraction_drafts", "run_id"),
        _sqlite_target("resemantica.db", "packet_metadata", "run_id"),
    ),
    "generic_run": (
        _sqlite_target("resemantica.db", "checkpoints", "run_id", release_column=None),
        _sqlite_target("resemantica.db", "runs", "run_id"),
    ),
}

_ALLOWED_SQLITE_TARGETS = {
    (str(target["database"]), str(target["table"]), str(target["column"]), target["release_column"])
    for targets in [*_RELEASE_SQLITE_TARGETS.values(), _TRACKING_SQLITE_TARGETS]
    for target in targets
}


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


def _validate_scope(scope: str) -> None:
    if scope not in CLEANUP_SCOPES:
        raise ValueError(f"Unsupported cleanup scope: {scope}")


def _expected_cleanup_root(release_id: str, scope: str) -> Path:
    cfg = load_config()
    if scope == "factory":
        return Path(cfg.paths.artifact_root)
    return derive_paths(cfg, release_id=release_id).release_root


def _collect_scope_artifacts(
    release_id: str, run_id: str, scope: str
) -> tuple[list[Path], list[Path]]:
    _validate_scope(scope)
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
        global_graph_db = artifact_root / "graph.ladybug"
        if global_graph_db.exists():
            deletable.append(global_graph_db)
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
        for subdir in ["extracted", "summaries", "glossary", "idioms", "graph", "packets"]:
            target = release_root / subdir
            if target.exists():
                deletable.append(target)

    elif scope == "cache":
        cache_dir = release_root / ".cache"
        if cache_dir.exists():
            deletable.append(cache_dir)

    elif scope == "keep-extracted":
        run_translation_dir = release_root / "runs" / run_id / "translation"
        if run_translation_dir.exists():
            deletable.append(run_translation_dir)
        for subdir in ["summaries", "glossary", "idioms", "graph", "packets", ".cache"]:
            target = release_root / subdir
            if target.exists():
                deletable.append(target)
        extracted_dir = release_root / "extracted"
        if extracted_dir.exists():
            preserved.append(extracted_dir)

    elif scope == "all":
        for p in release_root.iterdir():
            if p.name in _PROTECTED_RELEASE_ARTIFACTS:
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


def _sqlite_targets_for_scope(scope: str) -> list[dict[str, Any]]:
    release_targets: list[dict[str, Any]] = []
    tracking_targets: list[dict[str, Any]] = []

    if scope == "factory" or scope == "cache":
        return []
    if scope == "translation":
        release_targets.extend(_RELEASE_SQLITE_TARGETS["translation"])
    elif scope == "preprocess":
        release_targets.extend(_RELEASE_SQLITE_TARGETS["extraction"])
        release_targets.extend(_RELEASE_SQLITE_TARGETS["preprocess_downstream"])
        release_targets.extend(_RELEASE_SQLITE_TARGETS["generic_run"])
    elif scope == "keep-extracted":
        tracking_targets.extend(_TRACKING_SQLITE_TARGETS)
        release_targets.extend(_RELEASE_SQLITE_TARGETS["translation"])
        release_targets.extend(_RELEASE_SQLITE_TARGETS["preprocess_downstream"])
        release_targets.extend(_RELEASE_SQLITE_TARGETS["generic_run"])
    elif scope in ("run", "all"):
        tracking_targets.extend(_TRACKING_SQLITE_TARGETS)
        release_targets.extend(_RELEASE_SQLITE_TARGETS["translation"])
        release_targets.extend(_RELEASE_SQLITE_TARGETS["extraction"])
        release_targets.extend(_RELEASE_SQLITE_TARGETS["preprocess_downstream"])
        release_targets.extend(_RELEASE_SQLITE_TARGETS["generic_run"])

    return [dict(target) for target in [*tracking_targets, *release_targets]]


def plan_cleanup(
    release_id: str,
    run_id: str,
    *,
    scope: str = "run",
    dry_run: bool = True,
) -> dict[str, Any]:
    _validate_scope(scope)
    plan_path = _get_cleanup_plan_path(release_id, scope=scope)

    deletable, preserved = _collect_scope_artifacts(release_id, run_id, scope)
    expected_root = _expected_cleanup_root(release_id, scope)
    sqlite_rows = _sqlite_targets_for_scope(scope)
    for target in sqlite_rows:
        target["release_id"] = release_id
        target["run_id"] = run_id

    plan: dict[str, Any] = {
        "release_id": release_id,
        "run_id": run_id,
        "scope": scope,
        "dry_run": dry_run,
        "deletable_artifacts": [str(p) for p in deletable],
        "preserved_artifacts": [str(p) for p in preserved],
        "sqlite_rows": sqlite_rows,
        "estimated_space_bytes": _estimate_size(deletable),
        "expected_root": str(expected_root),
        "created_at": datetime.now(UTC).isoformat(),
        "schema_version": SUPPORTED_CLEANUP_PLAN_SCHEMA,
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


def _failure_report(release_id: str, run_id: str, scope: str, message: str) -> dict[str, Any]:
    return {
        "success": False,
        "message": message,
        "release_id": release_id,
        "run_id": run_id,
        "scope": scope,
        "deleted_files": [],
        "deleted_dirs": [],
        "sqlite_rows_deleted": 0,
        "errors": [message],
    }


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _validate_plan(
    plan: dict[str, Any],
    *,
    release_id: str,
    run_id: str,
    scope: str,
    force: bool,
) -> str | None:
    if plan.get("schema_version") not in {"1.0", SUPPORTED_CLEANUP_PLAN_SCHEMA}:
        return f"Unsupported cleanup plan schema: {plan.get('schema_version')}"

    plan_scope = str(plan.get("scope", ""))
    if plan_scope not in CLEANUP_SCOPES:
        return f"Unsupported cleanup plan scope: {plan_scope}"
    if plan_scope != scope:
        if not force:
            return f"Plan scope {plan_scope} does not match requested scope {scope}"
        if plan_scope == "factory" or scope == "factory":
            return "Factory cleanup requires a factory cleanup plan"

    if scope == "factory":
        expected_root = _expected_cleanup_root("", "factory")
    else:
        if plan.get("release_id") != release_id:
            return f"Plan release {plan.get('release_id')} does not match requested release {release_id}"
        if plan.get("run_id") != run_id:
            return f"Plan run {plan.get('run_id')} does not match requested run {run_id}"
        expected_root = _expected_cleanup_root(release_id, scope)

    plan_root = plan.get("expected_root")
    if plan_root and Path(str(plan_root)).resolve() != expected_root.resolve():
        return f"Plan root {plan_root} does not match expected root {expected_root}"

    for artifact_str in plan.get("deletable_artifacts", []):
        target = Path(str(artifact_str))
        if not _is_under_root(target, expected_root):
            return f"Cleanup target outside expected root: {target}"

    return None


def _table_exists(conn: Any, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def _delete_sqlite_targets(
    conn: Any,
    targets: list[dict[str, Any]],
    *,
    database: str,
    release_id: str,
    run_id: str,
) -> int:
    deleted = 0
    for target in targets:
        if target.get("database") != database:
            continue
        table = str(target.get("table", ""))
        column = str(target.get("column", ""))
        release_column = target.get("release_column")
        allowed_key = (database, table, column, release_column)
        if allowed_key not in _ALLOWED_SQLITE_TARGETS:
            raise ValueError(f"Unsupported SQLite cleanup target: {database}.{table}.{column}")
        if not _table_exists(conn, table):
            continue
        if release_column:
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE {release_column} = ? AND {column} = ?",
                (release_id, run_id),
            )
        else:
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE {column} = ?",
                (run_id,),
            )
        deleted += max(cursor.rowcount, 0)
    conn.commit()
    return deleted


def _plan_sqlite_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    sqlite_rows = list(plan.get("sqlite_rows", []))
    if sqlite_rows and all("column" in row for row in sqlite_rows):
        return sqlite_rows
    scope = str(plan.get("scope", ""))
    if scope not in CLEANUP_SCOPES:
        return []
    rows = _sqlite_targets_for_scope(scope)
    for row in rows:
        row["release_id"] = plan.get("release_id", "")
        row["run_id"] = plan.get("run_id", "")
    return rows


def apply_cleanup(
    release_id: str,
    run_id: str,
    *,
    scope: str = "run",
    force: bool = False,
) -> dict[str, Any]:
    _validate_scope(scope)
    plan_path = _get_cleanup_plan_path(release_id, scope=scope)

    if not plan_path.exists():
        msg = "No cleanup plan found. Run cleanup-plan first."
        emit_event(
            run_id or "__factory__", release_id or "__factory__", "cleanup.apply_failed",
            "cleanup", severity="error", message=msg
        )
        return _failure_report(release_id, run_id, scope, msg)

    with open(plan_path) as f:
        plan = json.load(f)

    validation_error = _validate_plan(
        plan, release_id=release_id, run_id=run_id, scope=scope, force=force
    )
    if validation_error:
        emit_event(
            run_id or "__factory__", release_id or "__factory__", "cleanup.apply_failed",
            "cleanup", severity="error", message=validation_error
        )
        return _failure_report(release_id, run_id, scope, validation_error)

    report: dict[str, Any] = {
        "success": True,
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
                report["sqlite_rows_deleted"] += _delete_sqlite_targets(
                    conn,
                    _plan_sqlite_rows(plan),
                    database="tracking.db",
                    release_id=release_id,
                    run_id=run_id,
                )
            finally:
                conn.close()
        except Exception as exc:
            report["errors"].append(f"Tracking SQLite cleanup error: {exc}")

        try:
            cfg = load_config()
            paths = derive_paths(cfg, release_id=release_id)
            conn = open_connection(paths.db_path)
            try:
                report["sqlite_rows_deleted"] += _delete_sqlite_targets(
                    conn,
                    _plan_sqlite_rows(plan),
                    database="resemantica.db",
                    release_id=release_id,
                    run_id=run_id,
                )
            finally:
                conn.close()
        except Exception as exc:
            report["errors"].append(f"Release SQLite cleanup error: {exc}")

    report_path = _get_cleanup_report_path(release_id, scope=scope)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report["errors"]:
        report["success"] = False
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    emit_event(
        run_id or "__factory__", release_id or "__factory__", "cleanup.apply_completed",
        "cleanup",
        message=f"Cleanup applied: {len(report['deleted_files'])} files, {len(report['deleted_dirs'])} dirs deleted",
        payload=report
    )

    return report
