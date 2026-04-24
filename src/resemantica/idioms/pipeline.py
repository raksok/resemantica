from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from resemantica.db.idiom_repo import (
    ensure_idiom_schema,
    find_exact_policy,
    insert_conflicts,
    insert_detected_candidates,
    list_candidates,
    list_candidates_for_promotion,
    list_conflicts,
    list_policies,
    mark_candidate_approved,
    mark_candidate_conflict,
    promote_policies,
)
from resemantica.db.sqlite import open_connection
from resemantica.idioms.extractor import extract_idioms
from resemantica.idioms.validators import normalize_idiom_source, validate_idiom_policy
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import load_prompt
from resemantica.settings import AppConfig, derive_paths, load_config


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _build_llm_client(config: AppConfig, llm_client: LLMClient | None) -> LLMClient:
    if llm_client is not None:
        return llm_client
    return LLMClient(
        base_url=config.llm.base_url,
        timeout_seconds=config.llm.timeout_seconds,
        max_retries=config.llm.max_retries,
    )


def _write_candidate_snapshot(conn: Any, *, release_id: str, output_path: Path) -> None:
    candidates = [candidate.to_json_dict() for candidate in list_candidates(conn, release_id=release_id)]
    _write_json(
        output_path,
        {
            "release_id": release_id,
            "schema_version": 1,
            "candidates": candidates,
        },
    )


def _write_policy_snapshot(conn: Any, *, release_id: str, output_path: Path) -> None:
    policies = [policy.to_json_dict() for policy in list_policies(conn, release_id=release_id)]
    _write_json(
        output_path,
        {
            "release_id": release_id,
            "schema_version": 1,
            "policies": policies,
        },
    )


def _write_conflict_snapshot(conn: Any, *, release_id: str, output_path: Path) -> None:
    conflicts = [conflict.to_json_dict() for conflict in list_conflicts(conn, release_id=release_id)]
    _write_json(
        output_path,
        {
            "release_id": release_id,
            "schema_version": 1,
            "conflicts": conflicts,
        },
    )


def preprocess_idioms(
    *,
    release_id: str,
    run_id: str = "idioms",
    config: AppConfig | None = None,
    project_root: Path | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    prompt = load_prompt("idiom_detect.txt")
    client = _build_llm_client(config_obj, llm_client)

    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        detected_candidates = extract_idioms(
            release_id=release_id,
            extracted_chapters_dir=paths.extracted_chapters_dir,
            detection_run_id=run_id,
            llm_client=client,
            model_name=config_obj.models.analyst_name,
            prompt_template=prompt.template,
            prompt_version=prompt.version,
        )
        insert_detected_candidates(conn, candidates=detected_candidates)

        pending_candidates = list_candidates_for_promotion(conn, release_id=release_id)
        existing_policies = list_policies(conn, release_id=release_id)
        validation = validate_idiom_policy(
            candidates=pending_candidates,
            existing_policies=existing_policies,
            approval_run_id=run_id,
        )
        insert_conflicts(conn, conflicts=validation.conflicts)
        promote_policies(conn, policies=validation.promotion_entries)

        reasons_by_candidate: dict[str, list[str]] = {}
        for conflict in validation.conflicts:
            reasons_by_candidate.setdefault(conflict.candidate_id, []).append(conflict.conflict_reason)
        for candidate_id, reasons in reasons_by_candidate.items():
            mark_candidate_conflict(conn, candidate_id=candidate_id, conflict_reason=" | ".join(reasons))
        for candidate_id in validation.promoted_candidate_ids:
            if candidate_id in reasons_by_candidate:
                continue
            mark_candidate_approved(conn, candidate_id=candidate_id)

        _write_candidate_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.idiom_candidates_path,
        )
        _write_policy_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.idiom_policies_path,
        )
        _write_conflict_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.idiom_conflicts_path,
        )
    finally:
        conn.close()

    chapters_seen = sorted(
        {
            candidate.first_seen_chapter
            for candidate in detected_candidates
        }
    )
    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "chapters_processed": len(chapters_seen),
        "candidates_written": len(detected_candidates),
        "promoted_count": len(validation.promotion_entries),
        "conflict_count": len(validation.conflicts),
        "candidates_artifact": str(paths.idiom_candidates_path),
        "policies_artifact": str(paths.idiom_policies_path),
        "conflicts_artifact": str(paths.idiom_conflicts_path),
    }


def resolve_idiom_policy(
    *,
    release_id: str,
    source_text: str,
    fallback_rendering: str | None = None,
    config: AppConfig | None = None,
    project_root: Path | None = None,
) -> str | None:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        policy = find_exact_policy(
            conn,
            release_id=release_id,
            normalized_source_text=normalize_idiom_source(source_text),
        )
        if policy is not None:
            return policy.preferred_rendering_en
        return fallback_rendering
    finally:
        conn.close()

