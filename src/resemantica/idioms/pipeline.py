from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.db.idiom_repo import (
    find_exact_policy,
    insert_conflicts,
    list_candidates,
    list_candidates_for_promotion,
    list_candidates_for_translation,
    list_conflicts,
    list_policies,
    mark_candidate_conflict,
    mark_candidate_promoted,
    promote_policies,
    save_idiom_translation,
    upsert_discovered_candidates,
)
from resemantica.db.sqlite import ensure_schema, open_connection
from resemantica.idioms.extractor import extract_idioms
from resemantica.idioms.validators import normalize_idiom_source, validate_idiom_policy
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import load_prompt, render_named_sections
from resemantica.orchestration.stop import StopToken, raise_if_stop_requested
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.utils import _build_llm_client, _chapter_number_from_path, _write_json
from resemantica.utils import _emit as _emit_shared

_STAGE_NAME = "preprocess-idioms"


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


def translate_idiom_candidates(
    *,
    conn: sqlite3.Connection,
    release_id: str,
    run_id: str,
    translator_client: LLMClient,
    translator_model_name: str,
    prompt_template: str,
    prompt_version: str,
    stop_token: StopToken | None = None,
) -> int:
    """Phase 2: Translate discovered idiom candidates using the Translator model."""
    pending = list_candidates_for_translation(conn, release_id=release_id)
    active_chapter: int | None = None
    completed_chapters: list[int] = []
    for candidate in pending:
        chapter = candidate.first_seen_chapter
        if active_chapter != chapter:
            if active_chapter is not None:
                completed_chapters.append(active_chapter)
                raise_if_stop_requested(
                    stop_token,
                    checkpoint={"idiom_translate_completed_chapters": completed_chapters},
                    message=f"Idiom translation stopped after chapter {active_chapter}",
                )
            raise_if_stop_requested(
                stop_token,
                checkpoint={"idiom_translate_completed_chapters": completed_chapters},
                message="Idiom translation stopped before next chapter",
            )
            active_chapter = chapter
        prompt = render_named_sections(
            prompt_template,
            sections={
                "SOURCE_TEXT": candidate.source_text,
                "MEANING_ZH": candidate.meaning_zh,
                "EVIDENCE_SNIPPET": candidate.evidence_snippet,
            },
        )
        rendered = translator_client.generate_text(
            model_name=translator_model_name,
            prompt=prompt,
        ).strip()
        save_idiom_translation(
            conn,
            candidate_id=candidate.candidate_id,
            translation_run_id=run_id,
            target_term=rendered,
            translator_model_name=translator_model_name,
            translator_prompt_version=prompt_version,
        )
    if active_chapter is not None:
        completed_chapters.append(active_chapter)
        raise_if_stop_requested(
            stop_token,
            checkpoint={"idiom_translate_completed_chapters": completed_chapters},
            message=f"Idiom translation stopped after chapter {active_chapter}",
        )
    return len(pending)


def preprocess_idioms(
    *,
    release_id: str,
    run_id: str = "idioms",
    config: AppConfig | None = None,
    project_root: Path | None = None,
    llm_client: LLMClient | None = None,
    translator_llm_client: LLMClient | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    stop_token: StopToken | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    chapter_refs = list_extracted_chapters(
        paths,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
    )

    detect_prompt = load_prompt("idiom_detect.txt")
    translate_prompt = load_prompt("idiom_translate.txt")
    analyst_client = _build_llm_client(config_obj, llm_client)
    translator_client = _build_llm_client(config_obj, translator_llm_client)

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "idioms")
    ensure_schema(conn, "summaries")
    try:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.started",
            total_chapters=len(chapter_refs),
        )
        # Phase 1: Detect (Analyst)
        skip_chapters: set[int] = set()
        cursor = conn.execute(
            "SELECT chapter_number FROM summary_drafts WHERE release_id = ? AND summary_type = 'chapter_summary_zh_structured' AND is_story_chapter = 0",
            (release_id,),
        )
        for row in cursor.fetchall():
            skip_chapters.add(int(row[0]))

        detected_candidates = extract_idioms(
            release_id=release_id,
            extracted_chapters_dir=paths.extracted_chapters_dir,
            detection_run_id=run_id,
            llm_client=analyst_client,
            model_name=config_obj.models.analyst_name,
            prompt_template=detect_prompt.template,
            prompt_version=detect_prompt.version,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
            skip_chapters=skip_chapters or None,
            config=config_obj,
            chapter_refs=chapter_refs,
            cache_root=paths.release_root / "cache" / "llm",
            event_callback=lambda event_name, chapter_number, payload: _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.{event_name}",
                chapter_number=chapter_number,
                **payload,
            ),
            stop_token=stop_token,
        )
        upsert_discovered_candidates(conn, candidates=detected_candidates)
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "detect_completed": True,
                "detected_candidates": len(detected_candidates),
            },
            message="Idiom preprocess stopped after detection",
        )

        # Phase 2: Translate (Translator)
        translated_count = translate_idiom_candidates(
            conn=conn,
            release_id=release_id,
            run_id=run_id,
            translator_client=translator_client,
            translator_model_name=config_obj.models.translator_name,
            prompt_template=translate_prompt.template,
            prompt_version=translate_prompt.version,
            stop_token=stop_token,
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "detect_completed": True,
                "translated_count": translated_count,
            },
            message="Idiom preprocess stopped after translation",
        )

        # Phase 3: Promote (no LLM)
        raise_if_stop_requested(
            stop_token,
            checkpoint={"promote_completed": False},
            message="Idiom promotion stopped before starting",
        )
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
            mark_candidate_promoted(conn, candidate_id=candidate_id)

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
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "promote_completed": True,
                "promoted_count": len(validation.promotion_entries),
            },
            message="Idiom preprocess stopped after promotion",
        )
    finally:
        conn.close()

    chapters_seen = sorted(
        {
            candidate.first_seen_chapter
            for candidate in detected_candidates
        }
    )
    skipped_count = len(chapter_refs) - len(chapters_seen)
    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.completed",
        extracted=len(detected_candidates),
        skipped=max(0, skipped_count),
        promoted_count=len(validation.promotion_entries),
    )
    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "chapters_processed": len(chapters_seen),
        "candidates_written": len(detected_candidates),
        "translated_count": translated_count,
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
    ensure_schema(conn, "idioms")
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
