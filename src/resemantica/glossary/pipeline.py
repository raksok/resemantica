from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.db.glossary_repo import (
    ensure_glossary_schema,
    find_exact_locked_entry,
    insert_conflicts,
    list_candidates,
    list_candidates_for_promotion,
    list_candidates_for_translation,
    list_conflicts,
    list_locked_entries,
    mark_candidate_conflict,
    mark_candidate_promoted,
    promote_locked_entries,
    save_candidate_translation,
    upsert_discovered_candidates,
)
from resemantica.db.sqlite import open_connection
from resemantica.glossary.discovery import discover_candidates_from_extracted
from resemantica.glossary.validators import normalize_term, validate_candidates_for_promotion
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import load_prompt
from resemantica.orchestration.events import emit_event
from resemantica.orchestration.stop import StopToken, raise_if_stop_requested
from resemantica.settings import AppConfig, derive_paths, load_config

_STAGE_NAME = "preprocess-glossary"


def _chapter_number_from_path(path: Path) -> int:
    return int(path.stem.split("-", 1)[1])


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


def _emit(run_id: str, release_id: str, event_type: str, **kwargs: object) -> None:
    chapter_number = kwargs.pop("chapter_number", None)
    message = str(kwargs.pop("message", ""))
    severity = str(kwargs.pop("severity", "info"))
    try:
        emit_event(
            run_id,
            release_id,
            event_type,
            _STAGE_NAME,
            chapter_number=chapter_number if isinstance(chapter_number, int) else None,
            severity=severity,
            message=message,
            payload=dict(kwargs),
        )
    except Exception:
        pass


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

    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        upsert_discovered_candidates(conn, candidates=discovered)
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
        f"{_STAGE_NAME}.discover.completed",
        discovered_count=len(discovered),
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
        "candidates_artifact": str(paths.glossary_candidates_path),
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

    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
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
    )

    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "translated_count": len(pending),
        "candidates_artifact": str(paths.glossary_candidates_path),
    }


def promote_glossary_candidates(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    stop_token: StopToken | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        raise_if_stop_requested(
            stop_token,
            checkpoint={"promote_completed": False},
            message="Glossary promotion stopped before starting",
        )
        _emit(run_id, release_id, f"{_STAGE_NAME}.promote.started")
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
    ensure_glossary_schema(conn)
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
