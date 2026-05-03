from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.db.glossary_repo import (
    find_exact_locked_entry,
    insert_conflicts,
    list_candidates,
    list_candidates_for_promotion,
    list_candidates_for_review,
    list_candidates_for_translation,
    list_conflicts,
    list_locked_entries,
    mark_candidate_conflict,
    mark_candidate_promoted,
    promote_locked_entries,
    save_candidate_translation,
    upsert_discovered_candidates,
)
from resemantica.db.sqlite import ensure_schema, open_connection
from resemantica.glossary.critic import compute_critic_scores
from resemantica.glossary.discovery import discover_candidates_from_extracted
from resemantica.glossary.models import GlossaryCandidate
from resemantica.glossary.validators import (
    apply_deterministic_filter,
    normalize_term,
    validate_candidates_for_promotion,
)
from resemantica.llm.client import LLMClient, capture_usage_snapshot, usage_payload_delta
from resemantica.llm.prompts import load_prompt
from resemantica.orchestration.stop import StopToken, raise_if_stop_requested
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.utils import _build_llm_client, _chapter_number_from_path, _write_json
from resemantica.utils import _emit as _emit_shared

_STAGE_NAME = "preprocess-glossary"


def _emit(run_id: str, release_id: str, event_type: str, **kwargs: object) -> None:
    _emit_shared(run_id, release_id, event_type, stage_name=_STAGE_NAME, **kwargs)


def _filtered_chapter_count(
    extracted_chapters_dir: Path,
    *,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
) -> int:
    chapter_files = sorted(
        extracted_chapters_dir.glob("chapter-*.json"),
        key=_chapter_number_from_path,
    )
    return len(
        [
            path
            for path in chapter_files
            if (chapter_start is None or _chapter_number_from_path(path) >= chapter_start)
            and (chapter_end is None or _chapter_number_from_path(path) <= chapter_end)
        ]
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


def discover_glossary_candidates(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    llm_client: LLMClient | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    pruning_threshold: float | None = None,
    stop_token: StopToken | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    prompt = load_prompt("glossary_discover.txt")
    client = _build_llm_client(config_obj, llm_client)
    chapter_refs = list_extracted_chapters(
        paths,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
    )
    usage_before = capture_usage_snapshot(client)
    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.started",
        total_chapters=len(chapter_refs),
    )
    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.discover.started",
        total_chapters=len(chapter_refs),
    )
    discovered = discover_candidates_from_extracted(
        release_id=release_id,
        extracted_chapters_dir=paths.extracted_chapters_dir,
        discovery_run_id=run_id,
        llm_client=client,
        model_name=config_obj.models.analyst_name,
        prompt_template=prompt.template,
        prompt_version=prompt.version,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        config=config_obj,
        chapter_refs=chapter_refs,
        cache_root=paths.release_root / "cache" / "llm",
        event_callback=lambda event_name, chapter_number, payload: _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.discover.{event_name}",
            chapter_number=chapter_number,
            **payload,
        ),
        stop_token=stop_token,
    )

    threshold = pruning_threshold if pruning_threshold is not None else config_obj.models.pruning_threshold

    # Tier 1: deterministic filter
    discovered = apply_deterministic_filter(discovered)
    # Tier 3: BGE-M3 embedding critic (skipped if threshold is 0 and we want eval-only,
    # but still score — handled inside compute_critic_scores)
    discovered = compute_critic_scores(
        discovered,
        model_name=config_obj.models.embedding_name,
        pruning_threshold=threshold,
    )

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "glossary")
    try:
        upsert_discovered_candidates(conn, candidates=discovered)
        _write_candidate_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.glossary_candidates_path,
        )
    finally:
        conn.close()

    filtered_count = sum(1 for c in discovered if c.candidate_status == "filtered")
    pruned_count = sum(1 for c in discovered if c.candidate_status == "pruned")
    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.discover.completed",
        discovered_count=len(discovered),
        filtered_count=filtered_count,
        pruned_count=pruned_count,
        **usage_payload_delta(client, usage_before),
    )
    raise_if_stop_requested(
        stop_token,
        checkpoint={"discover_completed": True, "candidates_written": len(discovered)},
        message="Glossary preprocess stopped after discovery",
    )

    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "candidates_written": len(discovered),
        "filtered_count": filtered_count,
        "pruned_count": pruned_count,
        "candidates_artifact": str(paths.glossary_candidates_path),
        **usage_payload_delta(client, usage_before),
    }


def translate_glossary_candidates(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    llm_client: LLMClient | None = None,
    stop_token: StopToken | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    prompt = load_prompt("glossary_translate.txt")
    client = _build_llm_client(config_obj, llm_client)
    usage_before = capture_usage_snapshot(client)

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "glossary")
    try:
        pending = list_candidates_for_translation(conn, release_id=release_id)
        chapters_with_pending = {candidate.first_seen_chapter for candidate in pending}
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.translate.started",
            total_chapters=len(chapters_with_pending),
        )
        active_chapter: int | None = None
        chapter_usage_before = capture_usage_snapshot(client)
        completed_chapters: list[int] = []
        for candidate in pending:
            chapter = candidate.first_seen_chapter
            if active_chapter != chapter:
                if active_chapter is not None:
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.translate.chapter_completed",
                        chapter_number=active_chapter,
                        candidate_count=sum(
                            1
                            for row in pending
                            if row.first_seen_chapter == active_chapter
                        ),
                        **usage_payload_delta(client, chapter_usage_before),
                    )
                    completed_chapters.append(active_chapter)
                    raise_if_stop_requested(
                        stop_token,
                        checkpoint={"translate_completed_chapters": completed_chapters},
                        message=f"Glossary translation stopped after chapter {active_chapter}",
                    )
                raise_if_stop_requested(
                    stop_token,
                    checkpoint={"translate_completed_chapters": completed_chapters},
                    message="Glossary translation stopped before next chapter",
                )
                active_chapter = chapter
                chapter_usage_before = capture_usage_snapshot(client)
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.translate.chapter_started",
                    chapter_number=chapter,
                )
            translated = client.translate_glossary_candidate(
                model_name=config_obj.models.translator_name,
                prompt_template=prompt.template,
                source_term=candidate.source_term,
                category=candidate.category,
                evidence_snippet=candidate.evidence_snippet,
            )
            normalized_target = normalize_term(translated)
            save_candidate_translation(
                conn,
                candidate_id=candidate.candidate_id,
                translation_run_id=run_id,
                target_term=translated,
                normalized_target_term=normalized_target,
                translator_model_name=config_obj.models.translator_name,
                translator_prompt_version=prompt.version,
            )
        if active_chapter is not None:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.translate.chapter_completed",
                chapter_number=active_chapter,
                candidate_count=sum(
                    1
                    for row in pending
                    if row.first_seen_chapter == active_chapter
                ),
                **usage_payload_delta(client, chapter_usage_before),
            )
            completed_chapters.append(active_chapter)
            raise_if_stop_requested(
                stop_token,
                checkpoint={"translate_completed_chapters": completed_chapters},
                message=f"Glossary translation stopped after chapter {active_chapter}",
            )

        _write_candidate_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.glossary_candidates_path,
        )
    finally:
        conn.close()

    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.translate.completed",
        translated_count=len(pending),
        **usage_payload_delta(client, usage_before),
    )

    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "translated_count": len(pending),
        "candidates_artifact": str(paths.glossary_candidates_path),
        **usage_payload_delta(client, usage_before),
    }


def promote_glossary_candidates(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    review_file_path: Path | None = None,
    stop_token: StopToken | None = None,
    llm_usage_payload: dict[str, int] | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "glossary")
    try:
        raise_if_stop_requested(
            stop_token,
            checkpoint={"promote_completed": False},
            message="Glossary promotion stopped before starting",
        )
        _emit(run_id, release_id, f"{_STAGE_NAME}.promote.started")

        if review_file_path is not None:
            if not review_file_path.exists():
                raise FileNotFoundError(f"Review file not found: {review_file_path}")
            review_data = json.loads(review_file_path.read_text(encoding="utf-8"))
            if review_data.get("review_schema_version") != 1:
                raise ValueError(
                    f"Unsupported review schema version: {review_data.get('review_schema_version')}"
                )
            promotable_candidates = _apply_review_overrides(
                conn, release_id=release_id, review_data=review_data
            )
        else:
            promotable_candidates = list_candidates_for_promotion(conn, release_id=release_id)

        existing_entries = list_locked_entries(conn, release_id=release_id)
        promotion_entries, conflicts = validate_candidates_for_promotion(
            candidates=promotable_candidates,
            existing_entries=existing_entries,
            approval_run_id=run_id,
        )

        insert_conflicts(conn, conflicts=conflicts)

        reasons_by_candidate: dict[str, list[str]] = {}
        for conflict in conflicts:
            reasons_by_candidate.setdefault(conflict.candidate_id, []).append(conflict.conflict_reason)
        for candidate_id, reasons in reasons_by_candidate.items():
            mark_candidate_conflict(conn, candidate_id=candidate_id, conflict_reason=" | ".join(reasons))

        promotable_without_conflicts = [
            entry
            for entry in promotion_entries
            if entry.source_candidate_id not in reasons_by_candidate
        ]
        promote_locked_entries(conn, entries=promotable_without_conflicts)
        for entry in promotable_without_conflicts:
            mark_candidate_promoted(conn, candidate_id=entry.source_candidate_id)

        _write_candidate_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.glossary_candidates_path,
        )
        _write_conflict_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.glossary_conflicts_path,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.promote.completed",
            promoted_count=len(promotable_without_conflicts),
            **(llm_usage_payload or {}),
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "promote_completed": True,
                "promoted_count": len(promotable_without_conflicts),
            },
            message="Glossary preprocess stopped after promotion",
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.completed",
            discovered=len(list_candidates(conn, release_id=release_id)),
            translated=len(promotable_candidates),
            promoted=len(promotable_without_conflicts),
            **(llm_usage_payload or {}),
        )
    finally:
        conn.close()

    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "candidate_count": len(promotable_candidates),
        "promoted_count": len(promotable_without_conflicts),
        "conflict_count": len(conflicts),
        "candidates_artifact": str(paths.glossary_candidates_path),
        "conflicts_artifact": str(paths.glossary_conflicts_path),
        **(llm_usage_payload or {}),
    }


def _is_add_entry(entry: dict[str, Any]) -> bool:
    return entry.get("action") == "add" and bool(entry.get("source_term"))


def _apply_review_overrides(
    conn: Any,
    *,
    release_id: str,
    review_data: dict[str, Any],
) -> list[GlossaryCandidate]:
    from hashlib import sha256 as _sha256

    from resemantica.db.glossary_repo import list_candidates as _list_candidates

    if not isinstance(review_data.get("entries"), list):
        raise ValueError("review_data must contain an 'entries' list")

    entry_by_id: dict[str, dict[str, Any]] = {}
    add_entries: list[dict[str, Any]] = []
    for entry in review_data["entries"]:
        cid = entry.get("candidate_id")
        if cid:
            entry_by_id[cid] = entry
        elif _is_add_entry(entry):
            add_entries.append(entry)

    all_candidates = {c.candidate_id: c for c in _list_candidates(conn, release_id=release_id)}
    applied_ids: set[str] = set()

    for cid, review_entry in entry_by_id.items():
        if review_entry.get("action") == "delete":
            continue
        candidate = all_candidates.get(cid)
        if candidate is None:
            continue
        new_translation = str(review_entry.get("translation", "")).strip()
        old_translation = (candidate.candidate_translation_en or "").strip()
        if new_translation and new_translation != old_translation:
            normalized = normalize_term(new_translation)
            conn.execute(
                """
                UPDATE glossary_candidates
                SET candidate_translation_en = ?,
                    normalized_target_term = ?,
                    candidate_status = 'translated',
                    validation_status = 'pending',
                    conflict_reason = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE candidate_id = ?
                """,
                (new_translation, normalized, cid),
            )
        applied_ids.add(cid)

    if add_entries:
        new_cands: list[GlossaryCandidate] = []
        for entry in add_entries:
            source_term = str(entry.get("source_term", "")).strip()
            category = str(entry.get("category", "generic_role")).strip()
            translation = str(entry.get("translation", "")).strip()
            if not source_term or not translation:
                continue
            normalized_source = normalize_term(source_term)
            digest = _sha256(f"{release_id}:review:{source_term}:{category}".encode()).hexdigest()[:24]
            candidate = GlossaryCandidate(
                candidate_id=f"gcan_review_{digest}",
                release_id=release_id,
                source_term=source_term,
                normalized_source_term=normalized_source,
                category=category,
                source_language="zh",
                first_seen_chapter=1,
                last_seen_chapter=1,
                appearance_count=1,
                evidence_snippet=str(entry.get("evidence_snippet", "")),
                candidate_translation_en=translation,
                normalized_target_term=normalize_term(translation),
                discovery_run_id="review",
                translation_run_id="review",
                candidate_status="translated",
                validation_status="pending",
                conflict_reason=None,
                critic_score=None,
                analyst_model_name=None,
                analyst_prompt_version=None,
                translator_model_name="human",
                translator_prompt_version="review",
                schema_version=1,
            )
            new_cands.append(candidate)
        if new_cands:
            upsert_discovered_candidates(conn, candidates=new_cands)
            for c in new_cands:
                all_candidates[c.candidate_id] = c
                applied_ids.add(c.candidate_id)

    deleted_ids = {cid for cid, re in entry_by_id.items() if re.get("action") == "delete"}
    result = []
    for cid in applied_ids:
        if cid in deleted_ids:
            continue
        candidate = all_candidates.get(cid)
        if candidate is not None and (candidate.candidate_translation_en or "").strip():
            result.append(candidate)
    return result


def review_glossary_candidates(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "glossary")
    try:
        candidates = list_candidates_for_review(conn, release_id=release_id)
    finally:
        conn.close()

    entries = [
        {
            "candidate_id": c.candidate_id,
            "source_term": c.source_term,
            "category": c.category,
            "translation": c.candidate_translation_en or "",
            "evidence_snippet": c.evidence_snippet,
            "action": "keep",
        }
        for c in candidates
    ]
    review_data = {
        "review_schema_version": 1,
        "release_id": release_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "instructions": (
            "Edit 'translation' to override a term's English rendering. "
            "Set 'action' to 'delete' to remove an entry. "
            "Add new entries with 'action': 'add' "
            "(omit candidate_id, provide source_term, category, translation, evidence_snippet)."
        ),
        "entries": entries,
    }
    _write_json(paths.glossary_review_path, review_data)
    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.review.completed",
        entries_written=len(entries),
        review_path=str(paths.glossary_review_path),
    )
    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "entries_written": len(entries),
        "review_path": str(paths.glossary_review_path),
    }


def resolve_locked_glossary_term(
    *,
    release_id: str,
    source_term: str,
    category: str,
    fallback_target_term: str | None = None,
    config: AppConfig | None = None,
    project_root: Path | None = None,
) -> str | None:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    conn = open_connection(paths.db_path)
    ensure_schema(conn, "glossary")
    try:
        exact = find_exact_locked_entry(
            conn,
            release_id=release_id,
            normalized_source_term=normalize_term(source_term),
            category=category,
        )
        if exact is not None:
            return exact.target_term
        return fallback_target_term
    finally:
        conn.close()
