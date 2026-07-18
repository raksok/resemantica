from __future__ import annotations

import csv
import json
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.db.idiom_repo import (
    clear_idiom_translation_for_run,
    count_complete_translation_vote_pairs_by_model,
    find_exact_policy,
    get_checkpoint,
    insert_conflicts,
    list_candidates,
    list_candidates_by_ids,
    list_candidates_for_promotion,
    list_candidates_for_review,
    list_candidates_for_translation,
    list_conflicts,
    list_existing_translation_vote_candidate_ids,
    list_policies,
    list_translation_resume_candidate_ids,
    list_translation_vote_candidate_ids_for_run,
    list_translation_votes,
    mark_candidates_conflict,
    mark_candidates_promoted,
    promote_policies,
    save_idiom_translation,
    set_checkpoint,
    set_translation_vote_resolution,
    upsert_discovered_candidates,
    upsert_translation_vote,
)
from resemantica.db.sqlite import ensure_schema, open_connection
from resemantica.idioms.extractor import extract_idioms
from resemantica.idioms.models import IdiomCandidate
from resemantica.idioms.validators import normalize_idiom_source, validate_idiom_policy
from resemantica.llm.client import LLMClient, capture_usage_snapshot, usage_payload_delta
from resemantica.llm.prompts import load_prompt, render_named_sections
from resemantica.orchestration.stop import StopRequested, StopToken, raise_if_stop_requested
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.utils import _build_llm_client, _write_json
from resemantica.utils import _emit as _emit_shared

_STAGE_NAME = "preprocess-idioms"
_TRANSLATION_RESUME_FETCH_CHUNK_SIZE = 500
_VOTE_KINDS = ("rendering", "meaning")


def _emit(run_id: str, release_id: str, event_type: str, **kwargs: object) -> None:
    _emit_shared(run_id, release_id, event_type, stage_name=_STAGE_NAME, **kwargs)


def _write_candidate_snapshot(conn: Any, *, release_id: str, output_path: Path) -> int:
    candidates = [candidate.to_json_dict() for candidate in list_candidates(conn, release_id=release_id)]
    _write_json(
        output_path,
        {
            "release_id": release_id,
            "schema_version": 1,
            "candidates": candidates,
        },
    )
    return len(candidates)


def _write_policy_snapshot(conn: Any, *, release_id: str, output_path: Path) -> int:
    policies = [policy.to_json_dict() for policy in list_policies(conn, release_id=release_id)]
    _write_json(
        output_path,
        {
            "release_id": release_id,
            "schema_version": 1,
            "policies": policies,
        },
    )
    return len(policies)


def _write_conflict_snapshot(conn: Any, *, release_id: str, output_path: Path) -> int:
    conflicts = [conflict.to_json_dict() for conflict in list_conflicts(conn, release_id=release_id)]
    _write_json(
        output_path,
        {
            "release_id": release_id,
            "schema_version": 1,
            "conflicts": conflicts,
        },
    )
    return len(conflicts)


def _clean_llm_response(text: str) -> str:
    text = re.sub(
        r'^(?:Category|Translation|Term|Evidence|Output|Result)\s*:\s*',
        '', text, flags=re.IGNORECASE | re.MULTILINE
    ).strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else text


def _chunks(values: list[str], chunk_size: int) -> list[list[str]]:
    return [values[index:index + chunk_size] for index in range(0, len(values), chunk_size)]


def _previous_translate_pending_count(
    *,
    tracking_db_path: Path,
    release_id: str,
    run_id: str,
) -> int | None:
    if not tracking_db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{tracking_db_path.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT payload_json
                FROM events
                WHERE release_id = ?
                  AND run_id = ?
                  AND event_type = ?
                ORDER BY event_time DESC
                LIMIT 1
                """,
                (release_id, run_id, f"{_STAGE_NAME}.translate.started"),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        logger.opt(exception=True).debug(
            "Could not read prior idiom translation start event from {}",
            tracking_db_path,
        )
        return None
    if row is None:
        return None
    try:
        payload = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError:
        logger.debug("Ignoring malformed prior idiom translation payload")
        return None
    pending_count = payload.get("pending_count")
    return pending_count if isinstance(pending_count, int) else None


def translate_idiom_candidates(
    *,
    conn: sqlite3.Connection,
    release_id: str,
    run_id: str,
    translator_client: LLMClient,
    translator_model_names: list[str],
    rendering_prompt_template: str,
    rendering_prompt_version: str,
    meaning_prompt_template: str,
    meaning_prompt_version: str,
    force: bool = False,
    stop_token: StopToken | None = None,
    event_callback: Callable[[str, dict[str, object]], None] | None = None,
    tracking_db_path: Path | None = None,
) -> int:
    """Phase 2: Translate discovered idiom candidates using the Translator model.
    Two calls per candidate: idiom rendering + meaning translation.
    """
    def _notify(event_name: str, **payload: object) -> None:
        if event_callback is not None:
            event_callback(event_name, payload)

    loading_started_at = time.perf_counter()
    _notify(
        "translate.loading_started",
        force=force,
        model_count=len(translator_model_names),
        message="Idiom translation loading started",
    )
    previous_pending_count: int | None = None
    resume_vote_model = ""
    resume_candidate_ids: list[str] = []
    complete_vote_counts_by_model: dict[str, int] = {}
    load_strategy = "canonical_pending_scan"
    pending_load_started_at = time.perf_counter()
    if force:
        pending = [
            candidate
            for candidate in list_candidates(conn, release_id=release_id)
            if candidate.candidate_status in {"discovered", "translated", "promoted"}
        ]
        load_strategy = "force_full_scan"
    else:
        if tracking_db_path is None:
            tracking_db_path = derive_paths(load_config(), release_id=release_id).release_root / "tracking.db"
        previous_pending_count = _previous_translate_pending_count(
            tracking_db_path=tracking_db_path,
            release_id=release_id,
            run_id=run_id,
        )
        complete_vote_counts_by_model = count_complete_translation_vote_pairs_by_model(
            conn,
            release_id=release_id,
            translation_run_id=run_id,
        )
        resume_vote_model = next(
            (
                model_name
                for model_name in translator_model_names
                if previous_pending_count is not None
                and complete_vote_counts_by_model.get(model_name) == previous_pending_count
            ),
            "",
        )
        if resume_vote_model:
            resume_candidate_ids = list_translation_resume_candidate_ids(
                conn,
                release_id=release_id,
                translation_run_id=run_id,
            )
            pending = []
            load_strategy = "vote_resume"
        else:
            pending = list_candidates_for_translation(conn, release_id=release_id)
    pending_load_seconds = time.perf_counter() - pending_load_started_at
    pending_count = len(resume_candidate_ids) if load_strategy == "vote_resume" else len(pending)
    chapters_with_pending = {candidate.first_seen_chapter for candidate in pending}
    loading_seconds = time.perf_counter() - loading_started_at
    _notify(
        "translate.loading_completed",
        force=force,
        pending_count=pending_count,
        candidate_count=pending_count,
        total_chapters=len(chapters_with_pending),
        model_count=len(translator_model_names),
        load_strategy=load_strategy,
        previous_pending_count=previous_pending_count,
        resume_vote_model=resume_vote_model,
        complete_vote_counts_by_model=complete_vote_counts_by_model,
        elapsed_seconds=round(loading_seconds, 3),
        pending_load_seconds=round(pending_load_seconds, 3),
        message=f"Idiom translation loading completed: {pending_count} candidates",
    )
    _notify(
        "translate.started",
        total_chapters=len(chapters_with_pending),
        pending_count=pending_count,
        candidate_count=pending_count,
        model_count=len(translator_model_names),
        message=f"Idiom translation started: {pending_count} pending candidates",
    )

    current_model_name = ""
    current_candidate_id = ""
    current_vote_kind = ""
    try:
        for model_name in translator_model_names:
            current_model_name = model_name
            vote_lookup_started_at = time.perf_counter()
            existing_vote_ids_by_kind = {
                vote_kind: (
                    set()
                    if force
                    else list_existing_translation_vote_candidate_ids(
                        conn,
                        release_id=release_id,
                        translation_run_id=run_id,
                        model_name=model_name,
                        vote_kind=vote_kind,
                    )
                )
                for vote_kind in _VOTE_KINDS
            }
            vote_lookup_seconds = time.perf_counter() - vote_lookup_started_at
            complete_existing_ids = set.intersection(
                existing_vote_ids_by_kind["rendering"],
                existing_vote_ids_by_kind["meaning"],
            )
            if load_strategy == "vote_resume":
                model_pending_ids = [
                    candidate_id
                    for candidate_id in resume_candidate_ids
                    if candidate_id not in complete_existing_ids
                ]
                model_pending = []
                model_candidate_count = len(model_pending_ids)
            else:
                model_pending = [
                    candidate
                    for candidate in pending
                    if candidate.candidate_id not in complete_existing_ids
                ]
                model_pending_ids = []
                model_candidate_count = len(model_pending)
            skipped_count = pending_count - model_candidate_count
            _notify(
                "translate.model_started",
                model_name=model_name,
                pending_count=pending_count,
                candidate_count=model_candidate_count,
                skipped_count=skipped_count,
                vote_lookup_seconds=round(vote_lookup_seconds, 3),
                message=f"Idiom translation model {model_name} started: {model_candidate_count} candidates",
            )
            generated_vote_count = 0
            candidate_batches: list[list[IdiomCandidate]]
            if load_strategy == "vote_resume":
                candidate_batches = [
                    list_candidates_by_ids(
                        conn,
                        release_id=release_id,
                        candidate_ids=candidate_id_batch,
                    )
                    for candidate_id_batch in _chunks(
                        model_pending_ids,
                        _TRANSLATION_RESUME_FETCH_CHUNK_SIZE,
                    )
                ]
            else:
                candidate_batches = [model_pending]
            for candidate_batch in candidate_batches:
                for candidate in candidate_batch:
                    current_candidate_id = candidate.candidate_id
                    if candidate.candidate_id not in existing_vote_ids_by_kind["rendering"]:
                        current_vote_kind = "rendering"
                        rendering_prompt = render_named_sections(
                            rendering_prompt_template,
                            sections={
                                "SOURCE_TEXT": candidate.source_text,
                                "EVIDENCE_SNIPPET": candidate.evidence_snippet,
                            },
                        )
                        raw_rendered = translator_client.generate_text(
                            model_name=model_name,
                            prompt=rendering_prompt,
                        )
                        rendered = _clean_llm_response(raw_rendered)
                        upsert_translation_vote(
                            conn,
                            candidate_id=candidate.candidate_id,
                            release_id=release_id,
                            translation_run_id=run_id,
                            model_name=model_name,
                            prompt_version=rendering_prompt_version,
                            vote_kind="rendering",
                            raw_output=raw_rendered,
                            cleaned_output=rendered,
                            normalized_output=_normalize_translation(rendered),
                        )
                        generated_vote_count += 1

                    if candidate.candidate_id not in existing_vote_ids_by_kind["meaning"]:
                        current_vote_kind = "meaning"
                        meaning_prompt = render_named_sections(
                            meaning_prompt_template,
                            sections={
                                "MEANING_ZH": candidate.meaning_zh,
                            },
                        )
                        raw_meaning = translator_client.generate_text(
                            model_name=model_name,
                            prompt=meaning_prompt,
                        )
                        meaning = _clean_llm_response(raw_meaning)
                        upsert_translation_vote(
                            conn,
                            candidate_id=candidate.candidate_id,
                            release_id=release_id,
                            translation_run_id=run_id,
                            model_name=model_name,
                            prompt_version=meaning_prompt_version,
                            vote_kind="meaning",
                            raw_output=raw_meaning,
                            cleaned_output=meaning,
                            normalized_output=_normalize_translation(meaning),
                        )
                        generated_vote_count += 1
            _notify(
                "translate.model_completed",
                model_name=model_name,
                pending_count=pending_count,
                candidate_count=model_candidate_count,
                skipped_count=skipped_count,
                generated_vote_count=generated_vote_count,
                message=f"Idiom translation model {model_name} completed: {model_candidate_count} candidates",
            )
    except Exception as exc:
        _notify(
            "translate.failed",
            severity="error",
            model_name=current_model_name,
            candidate_id=current_candidate_id,
            vote_kind=current_vote_kind,
            error=str(exc),
            message=(
                "Idiom translation failed"
                f" for model {current_model_name}, candidate {current_candidate_id}, {current_vote_kind}: {exc}"
            ),
        )
        logger.opt(exception=True).error(
            "Idiom translation failed for model {} candidate {} vote_kind={}: {}",
            current_model_name,
            current_candidate_id,
            current_vote_kind,
            exc,
        )
        raise

    translated_count = 0
    unresolved_count = 0
    unresolved_rendering_count = 0
    unresolved_meaning_count = 0
    active_chapter: int | None = None
    completed_chapters: list[int] = []
    chapter_candidate_count = 0
    chapter_translated_count = 0
    chapter_unresolved_count = 0
    _notify(
        "translate.resolution.started",
        pending_count=pending_count,
        candidate_count=pending_count,
        model_count=len(translator_model_names),
    )
    try:
        if load_strategy == "vote_resume":
            resolution_candidates = [
                candidate
                for candidate_id_batch in _chunks(
                    resume_candidate_ids,
                    _TRANSLATION_RESUME_FETCH_CHUNK_SIZE,
                )
                for candidate in list_candidates_by_ids(
                    conn,
                    release_id=release_id,
                    candidate_ids=candidate_id_batch,
                    preserve_input_order=False,
                )
            ]
            resolution_candidates.sort(
                key=lambda candidate: (
                    candidate.first_seen_chapter,
                    candidate.normalized_source_text,
                )
            )
        else:
            resolution_candidates = pending
        for candidate in resolution_candidates:
            current_candidate_id = candidate.candidate_id
            current_vote_kind = "resolution"
            chapter = candidate.first_seen_chapter
            if active_chapter != chapter:
                if active_chapter is not None:
                    _notify(
                        "translate.chapter_completed",
                        chapter_number=active_chapter,
                        candidate_count=chapter_candidate_count,
                        translated_count=chapter_translated_count,
                        unresolved_count=chapter_unresolved_count,
                    )
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
                chapter_candidate_count = 0
                chapter_translated_count = 0
                chapter_unresolved_count = 0
                _notify(
                    "translate.chapter_started",
                    chapter_number=chapter,
                )
            chapter_candidate_count += 1
            votes = list_translation_votes(
                conn,
                release_id=release_id,
                candidate_id=candidate.candidate_id,
            )
            votes = [vote for vote in votes if vote.translation_run_id == run_id]
            rendering_resolution = _resolve_translation_votes(
                [vote for vote in votes if vote.vote_kind == "rendering"],
                translator_model_names,
            )
            meaning_resolution = _resolve_translation_votes(
                [vote for vote in votes if vote.vote_kind == "meaning"],
                translator_model_names,
            )
            set_translation_vote_resolution(
                conn,
                candidate_id=candidate.candidate_id,
                translation_run_id=run_id,
                vote_kind="rendering",
                resolution_status=rendering_resolution["status"],
            )
            set_translation_vote_resolution(
                conn,
                candidate_id=candidate.candidate_id,
                translation_run_id=run_id,
                vote_kind="meaning",
                resolution_status=meaning_resolution["status"],
            )
            rendering_unresolved = not rendering_resolution["target_term"]
            meaning_unresolved = not meaning_resolution["target_term"]
            if rendering_unresolved or meaning_unresolved:
                unresolved_count += 1
                if rendering_unresolved:
                    unresolved_rendering_count += 1
                if meaning_unresolved:
                    unresolved_meaning_count += 1
            if rendering_resolution["target_term"]:
                current_vote_kind = "rendering"
                save_idiom_translation(
                    conn,
                    candidate_id=candidate.candidate_id,
                    translation_run_id=run_id,
                    target_term=rendering_resolution["target_term"],
                    meaning_en=meaning_resolution["target_term"],
                    translator_model_name=rendering_resolution["model_name"],
                    translator_prompt_version=rendering_prompt_version,
                )
                translated_count += 1
                chapter_translated_count += 1
            else:
                chapter_unresolved_count += 1
                _notify(
                    "translate.unresolved",
                    severity="debug",
                    candidate_id=candidate.candidate_id,
                    vote_kind="rendering",
                    unresolved_count=unresolved_count,
                    message=(
                        "Idiom translation unresolved for candidate "
                        f"{candidate.candidate_id}: rendering vote prevented saving"
                    ),
                )
    except Exception as exc:
        _notify(
            "translate.failed",
            severity="error",
            model_name=current_model_name,
            candidate_id=current_candidate_id,
            vote_kind=current_vote_kind,
            error=str(exc),
            message=(
                "Idiom translation failed"
                f" for candidate {current_candidate_id}, {current_vote_kind}: {exc}"
            ),
        )
        logger.opt(exception=True).error(
            "Idiom translation failed while resolving candidate {} vote_kind={}: {}",
            current_candidate_id,
            current_vote_kind,
            exc,
        )
        raise
    if active_chapter is not None:
        _notify(
            "translate.chapter_completed",
            chapter_number=active_chapter,
            candidate_count=chapter_candidate_count,
            translated_count=chapter_translated_count,
            unresolved_count=chapter_unresolved_count,
        )
        completed_chapters.append(active_chapter)
        raise_if_stop_requested(
            stop_token,
            checkpoint={"idiom_translate_completed_chapters": completed_chapters},
            message=f"Idiom translation stopped after chapter {active_chapter}",
        )
    _notify(
        "translate.resolution.completed",
        pending_count=pending_count,
        candidate_count=pending_count,
        translated_count=translated_count,
        unresolved_count=unresolved_count,
        unresolved_rendering_count=unresolved_rendering_count,
        unresolved_meaning_count=unresolved_meaning_count,
    )
    _notify(
        "translate.completed",
        severity="warning" if unresolved_count else "info",
        pending_count=pending_count,
        candidate_count=pending_count,
        translated_count=translated_count,
        unresolved_count=unresolved_count,
        unresolved_rendering_count=unresolved_rendering_count,
        unresolved_meaning_count=unresolved_meaning_count,
        message=(
            f"Idiom translation completed: {translated_count} translated, "
            f"{unresolved_count} unresolved"
        ),
    )
    return translated_count


def _normalize_translation(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _resolve_translation_votes(votes: list[Any], model_order: list[str]) -> dict[str, str]:
    votes_by_model = {vote.model_name: vote for vote in votes}
    ordered_votes = [votes_by_model[name] for name in model_order if name in votes_by_model]
    if not ordered_votes:
        return {"status": "unresolved", "target_term": "", "model_name": "", "prompt_version": ""}
    counts: dict[str, int] = {}
    for vote in ordered_votes:
        if vote.normalized_output:
            counts[vote.normalized_output] = counts.get(vote.normalized_output, 0) + 1
    if not counts:
        return {"status": "unresolved", "target_term": "", "model_name": "", "prompt_version": ""}
    winning_normalized, winning_count = max(counts.items(), key=lambda item: item[1])
    if winning_count <= len(ordered_votes) // 2:
        return {"status": "unresolved", "target_term": "", "model_name": "", "prompt_version": ""}
    status = "consensus" if winning_count == len(ordered_votes) else "majority"
    display_vote = next(vote for vote in ordered_votes if vote.normalized_output == winning_normalized)
    return {
        "status": status,
        "target_term": display_vote.cleaned_output,
        "model_name": display_vote.model_name,
        "prompt_version": display_vote.prompt_version,
    }


def _load_vote_resolution_candidates(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    translation_run_id: str,
) -> list[IdiomCandidate]:
    candidate_ids = list_translation_vote_candidate_ids_for_run(
        conn,
        release_id=release_id,
        translation_run_id=translation_run_id,
    )
    candidates = [
        candidate
        for candidate_id_batch in _chunks(candidate_ids, _TRANSLATION_RESUME_FETCH_CHUNK_SIZE)
        for candidate in list_candidates_by_ids(
            conn,
            release_id=release_id,
            candidate_ids=candidate_id_batch,
            preserve_input_order=False,
        )
    ]
    candidates.sort(
        key=lambda candidate: (
            candidate.first_seen_chapter,
            candidate.normalized_source_text,
        )
    )
    return candidates


def _apply_idiom_candidate_vote_resolution(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    translation_run_id: str,
    candidate: IdiomCandidate,
    translator_names: list[str],
    clear_stale_translation: bool = False,
) -> dict[str, object]:
    votes = [
        vote
        for vote in list_translation_votes(
            conn,
            release_id=release_id,
            candidate_id=candidate.candidate_id,
        )
        if vote.translation_run_id == translation_run_id
    ]
    rendering_resolution = _resolve_translation_votes(
        [vote for vote in votes if vote.vote_kind == "rendering"],
        translator_names,
    )
    meaning_resolution = _resolve_translation_votes(
        [vote for vote in votes if vote.vote_kind == "meaning"],
        translator_names,
    )
    set_translation_vote_resolution(
        conn,
        candidate_id=candidate.candidate_id,
        translation_run_id=translation_run_id,
        vote_kind="rendering",
        resolution_status=rendering_resolution["status"],
    )
    set_translation_vote_resolution(
        conn,
        candidate_id=candidate.candidate_id,
        translation_run_id=translation_run_id,
        vote_kind="meaning",
        resolution_status=meaning_resolution["status"],
    )
    if rendering_resolution["target_term"]:
        save_idiom_translation(
            conn,
            candidate_id=candidate.candidate_id,
            translation_run_id=translation_run_id,
            target_term=rendering_resolution["target_term"],
            meaning_en=meaning_resolution["target_term"] or candidate.meaning_en,
            translator_model_name=rendering_resolution["model_name"],
            translator_prompt_version=rendering_resolution["prompt_version"] or "unknown",
        )
        return {
            "rendering_resolution": rendering_resolution,
            "meaning_resolution": meaning_resolution,
            "translated": True,
            "unresolved": False,
            "cleared_stale": False,
        }

    cleared_stale = False
    if (
        clear_stale_translation
        and candidate.translation_run_id == translation_run_id
        and (candidate.preferred_rendering_en or "").strip()
    ):
        clear_idiom_translation_for_run(
            conn,
            candidate_id=candidate.candidate_id,
            translation_run_id=translation_run_id,
        )
        cleared_stale = True
    return {
        "rendering_resolution": rendering_resolution,
        "meaning_resolution": meaning_resolution,
        "translated": False,
        "unresolved": True,
        "cleared_stale": cleared_stale,
    }


def _load_idiom_fill_candidates(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    translation_run_id: str,
    translator_names: list[str],
) -> list[IdiomCandidate]:
    candidates = _load_vote_resolution_candidates(
        conn,
        release_id=release_id,
        translation_run_id=translation_run_id,
    )
    fill_candidates: list[IdiomCandidate] = []
    for candidate in candidates:
        if candidate.candidate_status == "approved":
            continue
        if (candidate.preferred_rendering_en or "").strip():
            continue
        votes = [
            vote
            for vote in list_translation_votes(
                conn,
                release_id=release_id,
                candidate_id=candidate.candidate_id,
            )
            if vote.translation_run_id == translation_run_id and vote.vote_kind == "rendering"
        ]
        resolution = _resolve_translation_votes(votes, translator_names)
        if not resolution["target_term"]:
            fill_candidates.append(candidate)
    return fill_candidates


def resolve_idiom_translation_votes(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    stop_token: StopToken | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    translator_names = config_obj.models.effective_preprocess_translator_names()
    phase = "start"
    conn = open_connection(paths.db_path)
    ensure_schema(conn, "idioms")
    try:
        raise_if_stop_requested(
            stop_token,
            checkpoint={"resolve_completed": False},
            message="Idiom vote resolution stopped before starting",
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.resolve.started",
            translation_run_id=run_id,
            model_count=len(translator_names),
            message="Idiom saved-vote resolution started",
        )

        phase = "load_candidates"
        candidates = [
            candidate
            for candidate in _load_vote_resolution_candidates(
                conn,
                release_id=release_id,
                translation_run_id=run_id,
            )
            if candidate.candidate_status != "approved"
        ]
        raise_if_stop_requested(
            stop_token,
            checkpoint={"phase": "candidates_loaded", "candidate_count": len(candidates)},
            message="Idiom vote resolution stopped after loading candidates",
        )

        phase = "resolve_votes"
        translated_count = 0
        unresolved_count = 0
        stale_cleared_count = 0
        meaning_unresolved_count = 0
        for candidate in candidates:
            result = _apply_idiom_candidate_vote_resolution(
                conn,
                release_id=release_id,
                translation_run_id=run_id,
                candidate=candidate,
                translator_names=translator_names,
                clear_stale_translation=True,
            )
            meaning_resolution = result["meaning_resolution"]
            if isinstance(meaning_resolution, dict) and not meaning_resolution.get("target_term"):
                meaning_unresolved_count += 1
            if result["translated"]:
                translated_count += 1
            else:
                unresolved_count += 1
                if result["cleared_stale"]:
                    stale_cleared_count += 1
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.resolve.unresolved",
                    severity="debug",
                    candidate_id=candidate.candidate_id,
                    source_text=candidate.source_text,
                    chapter_number=candidate.first_seen_chapter,
                    vote_kind="rendering",
                    unresolved_count=unresolved_count,
                    message=(
                        "Idiom saved-vote resolution unresolved for candidate "
                        f"{candidate.candidate_id}: no rendering majority vote"
                    ),
                )
            raise_if_stop_requested(
                stop_token,
                checkpoint={
                    "phase": "resolve_votes",
                    "translated_count": translated_count,
                    "unresolved_count": unresolved_count,
                },
                message="Idiom vote resolution stopped while resolving candidates",
            )

        phase = "write_candidates_snapshot"
        snapshot_count = _write_candidate_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.idiom_candidates_path,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.resolve.snapshot.artifact_written",
            artifact_path=str(paths.idiom_candidates_path),
            artifact_format="json",
            candidate_count=snapshot_count,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.resolve.completed",
            severity="warning" if unresolved_count else "info",
            translation_run_id=run_id,
            candidate_count=len(candidates),
            translated_count=translated_count,
            unresolved_count=unresolved_count,
            meaning_unresolved_count=meaning_unresolved_count,
            stale_cleared_count=stale_cleared_count,
            candidates_artifact=str(paths.idiom_candidates_path),
        )
    except StopRequested:
        raise
    except Exception as exc:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.resolve.failed",
            severity="error",
            phase=phase,
            error=str(exc),
            message=f"Idiom saved-vote resolution failed during {phase}: {exc}",
        )
        logger.opt(exception=True).error(
            "Idiom saved-vote resolution failed during {}: {}",
            phase,
            exc,
        )
        raise
    finally:
        conn.close()

    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "candidate_count": len(candidates),
        "translated_count": translated_count,
        "unresolved_count": unresolved_count,
        "meaning_unresolved_count": meaning_unresolved_count,
        "stale_cleared_count": stale_cleared_count,
        "candidates_artifact": str(paths.idiom_candidates_path),
    }


def fill_idiom_translation_votes(
    *,
    release_id: str,
    run_id: str,
    filler_model_names: list[str],
    config: AppConfig | None = None,
    project_root: Path | None = None,
    llm_client: LLMClient | None = None,
    force: bool = False,
    stop_token: StopToken | None = None,
) -> dict[str, Any]:
    if not filler_model_names:
        raise ValueError("At least one filler model is required.")
    filler_model_names = list(dict.fromkeys(filler_model_names))
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    translator_names = config_obj.models.effective_preprocess_translator_names()
    duplicate_models = set(translator_names).intersection(filler_model_names)
    if duplicate_models:
        names = ", ".join(sorted(duplicate_models))
        raise ValueError(f"Filler models must be distinct from translator models: {names}")
    model_order = [*translator_names, *filler_model_names]
    client = _build_llm_client(config_obj, llm_client)
    usage_before = capture_usage_snapshot(client)
    prompt = load_prompt("idiom_translate.txt")
    phase = "start"
    conn = open_connection(paths.db_path)
    ensure_schema(conn, "idioms")
    try:
        raise_if_stop_requested(
            stop_token,
            checkpoint={"fill_completed": False},
            message="Idiom filler stopped before starting",
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.fill.started",
            translation_run_id=run_id,
            filler_model_count=len(filler_model_names),
            force=force,
            vote_kind="rendering",
            message="Idiom filler started",
        )

        phase = "load_candidates"
        candidates = _load_idiom_fill_candidates(
            conn,
            release_id=release_id,
            translation_run_id=run_id,
            translator_names=translator_names,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.fill.loading_completed",
            candidate_count=len(candidates),
            filler_model_count=len(filler_model_names),
            force=force,
            vote_kind="rendering",
            message=f"Idiom filler loaded {len(candidates)} unresolved rendering candidates",
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint={"phase": "candidates_loaded", "candidate_count": len(candidates)},
            message="Idiom filler stopped after loading candidates",
        )

        phase = "vote_generation"
        filler_vote_count = 0
        skipped_vote_count = 0
        current_model_name = ""
        current_candidate_id = ""
        try:
            for model_name in filler_model_names:
                current_model_name = model_name
                existing_vote_candidate_ids = (
                    set()
                    if force
                    else list_existing_translation_vote_candidate_ids(
                        conn,
                        release_id=release_id,
                        translation_run_id=run_id,
                        model_name=model_name,
                        vote_kind="rendering",
                    )
                )
                model_pending = [
                    candidate
                    for candidate in candidates
                    if candidate.candidate_id not in existing_vote_candidate_ids
                ]
                model_skipped_count = len(candidates) - len(model_pending)
                skipped_vote_count += model_skipped_count
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.fill.model_started",
                    model_name=model_name,
                    candidate_count=len(model_pending),
                    skipped_count=model_skipped_count,
                    force=force,
                    vote_kind="rendering",
                    message=f"Idiom filler model {model_name} started: {len(model_pending)} renderings",
                )
                generated_count = 0
                for candidate in model_pending:
                    current_candidate_id = candidate.candidate_id
                    rendering_prompt = render_named_sections(
                        prompt.template,
                        sections={
                            "SOURCE_TEXT": candidate.source_text,
                            "EVIDENCE_SNIPPET": candidate.evidence_snippet,
                        },
                    )
                    raw_rendered = client.generate_text(
                        model_name=model_name,
                        prompt=rendering_prompt,
                    )
                    rendered = _clean_llm_response(raw_rendered)
                    upsert_translation_vote(
                        conn,
                        candidate_id=candidate.candidate_id,
                        release_id=release_id,
                        translation_run_id=run_id,
                        model_name=model_name,
                        prompt_version=prompt.version,
                        vote_kind="rendering",
                        raw_output=raw_rendered,
                        cleaned_output=rendered,
                        normalized_output=_normalize_translation(rendered),
                    )
                    generated_count += 1
                filler_vote_count += generated_count
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.fill.model_completed",
                    model_name=model_name,
                    candidate_count=generated_count,
                    skipped_count=model_skipped_count,
                    vote_kind="rendering",
                    message=f"Idiom filler model {model_name} completed: {generated_count} rendering votes",
                )
        except Exception as exc:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.fill.failed",
                severity="error",
                phase=phase,
                model_name=current_model_name,
                candidate_id=current_candidate_id,
                vote_kind="rendering",
                error=str(exc),
                message=(
                    "Idiom filler failed"
                    f" for model {current_model_name}, candidate {current_candidate_id}: {exc}"
                ),
            )
            raise

        phase = "resolve_votes"
        translated_count = 0
        unresolved_count = 0
        meaning_unresolved_count = 0
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.fill.resolution.started",
            candidate_count=len(candidates),
            filler_vote_count=filler_vote_count,
            skipped_vote_count=skipped_vote_count,
            vote_kind="rendering",
        )
        for candidate in candidates:
            result = _apply_idiom_candidate_vote_resolution(
                conn,
                release_id=release_id,
                translation_run_id=run_id,
                candidate=candidate,
                translator_names=model_order,
            )
            meaning_resolution = result["meaning_resolution"]
            if isinstance(meaning_resolution, dict) and not meaning_resolution.get("target_term"):
                meaning_unresolved_count += 1
            if result["translated"]:
                translated_count += 1
            else:
                unresolved_count += 1
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.fill.unresolved",
                    severity="debug",
                    candidate_id=candidate.candidate_id,
                    source_text=candidate.source_text,
                    chapter_number=candidate.first_seen_chapter,
                    vote_kind="rendering",
                    unresolved_count=unresolved_count,
                    message=(
                        "Idiom filler unresolved for candidate "
                        f"{candidate.candidate_id}: no rendering majority vote"
                    ),
                )
            raise_if_stop_requested(
                stop_token,
                checkpoint={
                    "phase": "resolve_votes",
                    "translated_count": translated_count,
                    "unresolved_count": unresolved_count,
                },
                message="Idiom filler stopped while resolving candidates",
            )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.fill.resolution.completed",
            candidate_count=len(candidates),
            translated_count=translated_count,
            unresolved_count=unresolved_count,
            meaning_unresolved_count=meaning_unresolved_count,
            vote_kind="rendering",
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.fill.completed",
            severity="warning" if unresolved_count else "info",
            translation_run_id=run_id,
            candidate_count=len(candidates),
            filler_vote_count=filler_vote_count,
            skipped_vote_count=skipped_vote_count,
            translated_count=translated_count,
            unresolved_count=unresolved_count,
            meaning_unresolved_count=meaning_unresolved_count,
            vote_kind="rendering",
            **usage_payload_delta(client, usage_before),
        )
    except StopRequested:
        raise
    except Exception as exc:
        if phase != "vote_generation":
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.fill.failed",
                severity="error",
                phase=phase,
                error=str(exc),
                message=f"Idiom filler failed during {phase}: {exc}",
            )
        raise
    finally:
        conn.close()

    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "candidate_count": len(candidates),
        "filler_vote_count": filler_vote_count,
        "skipped_vote_count": skipped_vote_count,
        "translated_count": translated_count,
        "unresolved_count": unresolved_count,
        "meaning_unresolved_count": meaning_unresolved_count,
        **usage_payload_delta(client, usage_before),
    }


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
    eval_batch_size: int | None = None,
    skip_llm_eval: bool = False,
    score_threshold: float | None = None,
    resume: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    chapter_refs = list_extracted_chapters(
        paths,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
    )

    detect_prompt = load_prompt("idiom_evaluate.txt")
    translate_prompt = load_prompt("idiom_translate.txt")
    meaning_prompt = load_prompt("idiom_meaning.txt")
    analyst_client = _build_llm_client(config_obj, llm_client)
    translator_client = _build_llm_client(config_obj, translator_llm_client)
    combined_usage_before = {
        "analyst": capture_usage_snapshot(analyst_client),
        "translator": capture_usage_snapshot(translator_client),
    }

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "idioms")
    ensure_schema(conn, "summaries")

    resume_stage = get_checkpoint(conn, release_id=release_id, run_id=run_id) if resume and not force else None
    if resume_stage:
        logger.info("Resuming idioms from checkpoint stage: {}", resume_stage)

    try:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.started",
            total_chapters=len(chapter_refs),
        )
        # Phase 1: Detect (Analyst)
        skip_chapters: set[int] = set()
        chapter_summaries: dict[int, dict] = {}
        try:
            cursor = conn.execute(
                "SELECT chapter_number, content_json, is_story_chapter FROM summary_drafts "
                "WHERE release_id = ? AND summary_type = 'chapter_summary_zh_structured'"
                "  AND validation_status IN ('approved', 'pending', 'non_story_chapter')",
                (release_id,),
            )
            for row in cursor.fetchall():
                ch = int(row[0])
                if int(row[2]) == 0:
                    skip_chapters.add(ch)
                raw = json.loads(row[1])
                content = raw.get("parsed_summary", raw)
                if isinstance(content, dict):
                    chapter_summaries[ch] = content
        except Exception:
            pass  # Table may not exist if summaries haven't run yet

        def _emit_extract_event(
            event_name: str,
            chapter_number: int | None,
            payload: dict[str, object],
        ) -> None:
            event_payload = dict(payload)
            if event_name == "eval_batch_error":
                event_payload.setdefault("severity", "warning")
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.{event_name}",
                chapter_number=chapter_number,
                **event_payload,
            )

        if resume_stage not in ("detect_completed", "translated", "promoted"):
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
                event_callback=_emit_extract_event,
                stop_token=stop_token,
                skip_llm_eval=skip_llm_eval,
                eval_batch_size=eval_batch_size or 50,
                score_threshold=score_threshold,
                chapter_summaries=chapter_summaries or None,
            )
            upsert_discovered_candidates(conn, candidates=detected_candidates)
            set_checkpoint(conn, release_id=release_id, run_id=run_id, stage_name="detect_completed")
        else:
            logger.info("Resuming idioms: skipping detect phase (checkpoint: {})", resume_stage)
            detected_candidates = list_candidates(conn, release_id=release_id)

        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "detect_completed": True,
                "detected_candidates": len(detected_candidates),
            },
            message="Idiom preprocess stopped after detection",
        )

        # Phase 2: Translate (Translator) — rendering + meaning
        if resume_stage not in ("translated", "promoted"):
            translated_count = translate_idiom_candidates(
                conn=conn,
                release_id=release_id,
                run_id=run_id,
                translator_client=translator_client,
                translator_model_names=config_obj.models.effective_preprocess_translator_names(),
                rendering_prompt_template=translate_prompt.template,
                rendering_prompt_version=translate_prompt.version,
                meaning_prompt_template=meaning_prompt.template,
                meaning_prompt_version=meaning_prompt.version,
                force=force,
                stop_token=stop_token,
                tracking_db_path=paths.release_root / "tracking.db",
                event_callback=lambda event_name, payload: _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.{event_name}",
                    **payload,
                ),
            )
            set_checkpoint(conn, release_id=release_id, run_id=run_id, stage_name="translated")
        else:
            logger.info("Resuming idioms: skipping translate phase")
            translated_count = 0

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
        pending_candidates = (
            [
                candidate
                for candidate in list_candidates(conn, release_id=release_id)
                if candidate.candidate_status in {"translated", "promoted"}
                and candidate.preferred_rendering_en
            ]
            if force
            else list_candidates_for_promotion(conn, release_id=release_id)
        )
        existing_policies = list_policies(conn, release_id=release_id)
        validation = validate_idiom_policy(
            candidates=pending_candidates,
            existing_policies=existing_policies,
            approval_run_id=run_id,
        )

        # All DB writes in a single transaction — batch via executemany
        with conn:
            if pending_candidates:
                _all_ids = [c.candidate_id for c in pending_candidates]
                _placeholders = ",".join("?" for _ in _all_ids)
                conn.execute(
                    f"DELETE FROM idiom_conflicts "
                    f"WHERE candidate_id IN ({_placeholders}) AND release_id = ?",
                    [*_all_ids, release_id],
                )
            insert_conflicts(conn, conflicts=validation.conflicts)
            promote_policies(conn, policies=validation.promotion_entries)

            reasons_by_candidate: dict[str, list[str]] = {}
            for conflict in validation.conflicts:
                reasons_by_candidate.setdefault(conflict.candidate_id, []).append(conflict.conflict_reason)
            mark_candidates_conflict(
                conn,
                conflicts=[(cid, " | ".join(reasons)) for cid, reasons in reasons_by_candidate.items()],
            )
            promoted_ids = [
                cid for cid in validation.promoted_candidate_ids
                if cid not in reasons_by_candidate
            ]
            mark_candidates_promoted(conn, candidate_ids=promoted_ids)

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
        set_checkpoint(conn, release_id=release_id, run_id=run_id, stage_name="promoted")
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
        **_merge_usage_payloads(
            usage_payload_delta(analyst_client, combined_usage_before["analyst"]),
            usage_payload_delta(translator_client, combined_usage_before["translator"]),
        ),
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
        **_merge_usage_payloads(
            usage_payload_delta(analyst_client, combined_usage_before["analyst"]),
            usage_payload_delta(translator_client, combined_usage_before["translator"]),
        ),
    }


def _is_add_idiom_entry(entry: dict[str, Any]) -> bool:
    return entry.get("action") == "add" and bool(entry.get("source_text"))


def _apply_idiom_review_overrides(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    review_data: dict[str, Any],
) -> list[IdiomCandidate]:
    from dataclasses import replace as _dataclass_replace
    from hashlib import sha256 as _sha256

    if not isinstance(review_data.get("entries"), list):
        raise ValueError("review_data must contain an 'entries' list")

    entry_by_id: dict[str, dict[str, Any]] = {}
    add_entries: list[dict[str, Any]] = []
    for entry in review_data["entries"]:
        cid = entry.get("candidate_id")
        if cid:
            entry_by_id[cid] = entry
        elif _is_add_idiom_entry(entry):
            add_entries.append(entry)

    all_candidates = {c.candidate_id: c for c in list_candidates(conn, release_id=release_id)}
    applied_ids: set[str] = set()

    for cid, review_entry in entry_by_id.items():
        if review_entry.get("action") == "delete":
            continue
        candidate = all_candidates.get(cid)
        if candidate is None:
            continue
        new_rendering = str(review_entry.get("rendering", "")).strip()
        old_rendering = candidate.preferred_rendering_en.strip()
        new_meaning_en = str(review_entry.get("meaning_en", "")).strip()
        old_meaning_en = candidate.meaning_en.strip()
        if (new_rendering and new_rendering != old_rendering) or (
            new_meaning_en and new_meaning_en != old_meaning_en
        ):
            rendering = new_rendering or candidate.preferred_rendering_en
            meaning_en = new_meaning_en or candidate.meaning_en
            conn.execute(
                """
                UPDATE idiom_candidates
                SET preferred_rendering_en = ?,
                    meaning_en = ?,
                    translation_run_id = 'review',
                    candidate_status = 'translated',
                    validation_status = 'pending',
                    conflict_reason = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE candidate_id = ?
                """,
                (rendering, meaning_en, cid),
            )
            all_candidates[cid] = _dataclass_replace(
                candidate,
                preferred_rendering_en=rendering,
                meaning_en=meaning_en,
                translation_run_id="review",
                candidate_status="translated",
                validation_status="pending",
                conflict_reason=None,
            )
        applied_ids.add(cid)

    if add_entries:
        new_cands: list[IdiomCandidate] = []
        for entry in add_entries:
            source_text = str(entry.get("source_text", "")).strip()
            rendering = str(entry.get("rendering", "")).strip()
            if not source_text or not rendering:
                continue
            normalized_source = normalize_idiom_source(source_text)
            digest = _sha256(f"{release_id}:review:{source_text}".encode()).hexdigest()[:24]
            candidate = IdiomCandidate(
                candidate_id=f"ican_review_{digest}",
                release_id=release_id,
                source_text=source_text,
                normalized_source_text=normalized_source,
                meaning_zh=str(entry.get("meaning_zh", "")),
                meaning_en=str(entry.get("meaning_en", "")),
                preferred_rendering_en=rendering,
                usage_notes=str(entry.get("usage_notes") or ""),
                first_seen_chapter=1,
                last_seen_chapter=1,
                appearance_count=1,
                evidence_snippet=str(entry.get("evidence_snippet", "")),
                detection_run_id="review",
                candidate_status="translated",
                validation_status="pending",
                conflict_reason=None,
                analyst_model_name="human",
                analyst_prompt_version="review",
                translation_run_id="review",
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
        if candidate is not None and candidate.preferred_rendering_en.strip():
            result.append(candidate)
    return result


_IDIOM_CSV_HEADER = [
    "action",
    "source_text",
    "meaning_zh",
    "meaning_en",
    "rendering",
    "candidate_id",
    "evidence_snippet",
    "alternatives",
]


def _write_idiom_review_csv(path: Path, entries: list[dict[str, Any]]) -> None:
    rows: list[list[str]] = [_IDIOM_CSV_HEADER]
    for entry in entries:
        snippet = entry.get("evidence_snippet") or ""
        snippet = snippet.replace("\n", " ").replace("\r", " ")
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        alts = [
            f"{alt.get('kind', '')}:{alt.get('translation', '')}"
            for alt in (entry.get("alternatives") or [])
        ]
        rows.append([
            entry.get("action") or "keep",
            entry.get("source_text") or "",
            entry.get("meaning_zh") or "",
            entry.get("meaning_en") or "",
            entry.get("rendering") or "",
            entry.get("candidate_id") or "",
            snippet,
            "|".join(alts),
        ])
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerows(rows)


def _read_idiom_review_csv(path: Path) -> dict[str, Any]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter="\t")
        raw_rows = list(reader)
    if not raw_rows:
        raise ValueError("Review CSV is empty")
    header = raw_rows[0]
    if header != _IDIOM_CSV_HEADER:
        raise ValueError(
            f"Review CSV has invalid header. Expected: {_IDIOM_CSV_HEADER!r}, got: {header!r}"
        )
    entries: list[dict[str, Any]] = []
    for row in raw_rows[1:]:
        if len(row) < len(_IDIOM_CSV_HEADER):
            row += [""] * (len(_IDIOM_CSV_HEADER) - len(row))
        action = row[0].strip().lower() if row[0].strip() else "keep"
        entries.append({
            "candidate_id": row[5].strip() or None,
            "source_text": row[1].strip(),
            "meaning_zh": row[2].strip(),
            "meaning_en": row[3].strip(),
            "rendering": row[4].strip(),
            "action": action,
            "evidence_snippet": row[6].strip(),
        })
    return {
        "review_schema_version": 1,
        "entries": entries,
    }


def _read_idiom_review_data(review_file_path: Path) -> dict[str, Any]:
    if review_file_path.suffix.lower() == ".csv":
        return _read_idiom_review_csv(review_file_path)
    review_data: dict[str, Any] = json.loads(review_file_path.read_text(encoding="utf-8"))
    if review_data.get("review_schema_version") != 1:
        raise ValueError(
            f"Unsupported review schema version: {review_data.get('review_schema_version')}"
        )
    return review_data


def review_idiom_candidates(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    stop_token: StopToken | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    phase = "load_candidates"

    try:
        raise_if_stop_requested(
            stop_token,
            checkpoint={"review_completed": False},
            message="Idiom review stopped before starting",
        )
        _emit(run_id, release_id, f"{_STAGE_NAME}.review.started")
        conn = open_connection(paths.db_path)
        ensure_schema(conn, "idioms")
        try:
            candidates = list_candidates_for_review(conn, release_id=release_id)
            votes = list_translation_votes(conn, release_id=release_id)
        finally:
            conn.close()
        raise_if_stop_requested(
            stop_token,
            checkpoint={"phase": "candidates_loaded", "candidate_count": len(candidates)},
            message="Idiom review stopped after loading candidates",
        )

        phase = "build_review"
        model_order = {
            model_name: index
            for index, model_name in enumerate(config_obj.models.effective_preprocess_translator_names())
        }
        votes_by_candidate: dict[str, list[Any]] = {}
        for vote in votes:
            votes_by_candidate.setdefault(vote.candidate_id, []).append(vote)
        for candidate_votes in votes_by_candidate.values():
            candidate_votes.sort(
                key=lambda vote: (
                    vote.vote_kind,
                    model_order.get(vote.model_name, len(model_order)),
                )
            )

        entries = [
            {
                "candidate_id": c.candidate_id,
                "source_text": c.source_text,
                "meaning_zh": c.meaning_zh,
                "meaning_en": c.meaning_en,
                "rendering": c.preferred_rendering_en,
                "evidence_snippet": c.evidence_snippet,
                "alternatives": [
                    {
                        "model_name": vote.model_name,
                        "kind": vote.vote_kind,
                        "translation": vote.cleaned_output,
                        "resolution_status": vote.resolution_status,
                    }
                    for vote in votes_by_candidate.get(c.candidate_id, [])
                ],
                "action": "keep",
            }
            for c in candidates
        ]
        review_data = {
            "review_schema_version": 1,
            "release_id": release_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "instructions": (
                "Edit 'rendering' to override an idiom's English translation. "
                "Set 'action' to 'delete' to remove an entry. "
                "Add new entries with 'action': 'add' "
                "(omit candidate_id, provide source_text, meaning_zh, rendering)."
            ),
            "entries": entries,
        }
        review_csv_path = paths.idiom_review_path.with_suffix(".csv")
        phase = "write_review_json"
        raise_if_stop_requested(
            stop_token,
            checkpoint={"phase": "review_json_pending", "entries_written": len(entries)},
            message="Idiom review stopped before writing review JSON",
        )
        _write_json(paths.idiom_review_path, review_data)
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.review.json.artifact_written",
            artifact_path=str(paths.idiom_review_path),
            artifact_format="json",
            entries_written=len(entries),
        )
        phase = "write_review_csv"
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "review_json_written",
                "entries_written": len(entries),
                "review_json_path": str(paths.idiom_review_path),
            },
            message="Idiom review stopped after writing review JSON",
        )
        _write_idiom_review_csv(review_csv_path, entries)
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.review.csv.artifact_written",
            artifact_path=str(review_csv_path),
            artifact_format="tsv",
            entries_written=len(entries),
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "review_csv_written",
                "entries_written": len(entries),
                "review_json_path": str(paths.idiom_review_path),
                "review_csv_path": str(review_csv_path),
            },
            message="Idiom review stopped after writing review CSV",
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.review.completed",
            entries_written=len(entries),
            review_path=str(paths.idiom_review_path),
            review_json_path=str(paths.idiom_review_path),
            review_csv_path=str(review_csv_path),
        )
        return {
            "status": "success",
            "release_id": release_id,
            "run_id": run_id,
            "entries_written": len(entries),
            "review_path": str(paths.idiom_review_path),
            "review_json_path": str(paths.idiom_review_path),
            "review_csv_path": str(review_csv_path),
        }
    except StopRequested:
        raise
    except Exception as exc:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.review.failed",
            severity="error",
            phase=phase,
            error=str(exc),
            message=f"Idiom review failed during {phase}: {exc}",
        )
        raise


def promote_idiom_candidates(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    review_file_path: Path | None = None,
    stop_token: StopToken | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "idioms")
    phase = "start"
    try:
        raise_if_stop_requested(
            stop_token,
            checkpoint={"promote_completed": False},
            message="Idiom promotion stopped before starting",
        )
        _emit(run_id, release_id, f"{_STAGE_NAME}.promote.started")

        if review_file_path is not None:
            phase = "review_file"
            if not review_file_path.exists():
                raise FileNotFoundError(f"Review file not found: {review_file_path}")
            review_data = _read_idiom_review_data(review_file_path)
            raise_if_stop_requested(
                stop_token,
                checkpoint={"phase": "review_file_loaded"},
                message="Idiom promotion stopped after reading review file",
            )
            pending_candidates = _apply_idiom_review_overrides(
                conn, release_id=release_id, review_data=review_data
            )
            raise_if_stop_requested(
                stop_token,
                checkpoint={"phase": "review_overrides_applied"},
                message="Idiom promotion stopped after applying review overrides",
            )
        else:
            phase = "load_candidates"
            pending_candidates = list_candidates_for_promotion(conn, release_id=release_id)
            raise_if_stop_requested(
                stop_token,
                checkpoint={"phase": "candidates_loaded"},
                message="Idiom promotion stopped after loading candidates",
            )

        phase = "validation"
        raise_if_stop_requested(
            stop_token,
            checkpoint={"phase": "validation_pending"},
            message="Idiom promotion stopped before validation",
        )
        existing_policies = list_policies(conn, release_id=release_id)
        validation = validate_idiom_policy(
            candidates=pending_candidates,
            existing_policies=existing_policies,
            approval_run_id=run_id,
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "validation_completed",
                "candidate_count": len(pending_candidates),
                "conflict_count": len(validation.conflicts),
            },
            message="Idiom promotion stopped after validation",
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "promotion_pending",
                "promoted_count": len(validation.promotion_entries),
                "conflict_count": len(validation.conflicts),
            },
            message="Idiom promotion stopped before writing policies",
        )

        # All DB writes in a single transaction — batch via executemany
        with conn:
            if pending_candidates:
                _all_ids = [c.candidate_id for c in pending_candidates]
                _placeholders = ",".join("?" for _ in _all_ids)
                conn.execute(
                    f"DELETE FROM idiom_conflicts "
                    f"WHERE candidate_id IN ({_placeholders}) AND release_id = ?",
                    [*_all_ids, release_id],
                )
            insert_conflicts(conn, conflicts=validation.conflicts)
            promote_policies(conn, policies=validation.promotion_entries)

            reasons_by_candidate: dict[str, list[str]] = {}
            for conflict in validation.conflicts:
                reasons_by_candidate.setdefault(conflict.candidate_id, []).append(conflict.conflict_reason)
            mark_candidates_conflict(
                conn,
                conflicts=[(cid, " | ".join(reasons)) for cid, reasons in reasons_by_candidate.items()],
            )
            promoted_ids = [
                cid for cid in validation.promoted_candidate_ids
                if cid not in reasons_by_candidate
            ]
            mark_candidates_promoted(conn, candidate_ids=promoted_ids)
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "promotion_written",
                "promoted_count": len(validation.promotion_entries),
                "conflict_count": len(validation.conflicts),
            },
            message="Idiom promotion stopped after writing policies",
        )

        phase = "write_candidates_snapshot"
        raise_if_stop_requested(
            stop_token,
            checkpoint={"phase": "candidates_snapshot_pending"},
            message="Idiom promotion stopped before candidate snapshot",
        )
        candidate_snapshot_count = _write_candidate_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.idiom_candidates_path,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.promote.candidates.artifact_written",
            artifact_path=str(paths.idiom_candidates_path),
            artifact_format="json",
            candidate_count=candidate_snapshot_count,
        )
        phase = "write_policies_snapshot"
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "candidates_snapshot_written",
                "candidates_artifact": str(paths.idiom_candidates_path),
            },
            message="Idiom promotion stopped after candidate snapshot",
        )
        policy_snapshot_count = _write_policy_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.idiom_policies_path,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.promote.policies.artifact_written",
            artifact_path=str(paths.idiom_policies_path),
            artifact_format="json",
            policy_count=policy_snapshot_count,
        )
        phase = "write_conflicts_snapshot"
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "policies_snapshot_written",
                "candidates_artifact": str(paths.idiom_candidates_path),
                "policies_artifact": str(paths.idiom_policies_path),
            },
            message="Idiom promotion stopped after policy snapshot",
        )
        conflict_snapshot_count = _write_conflict_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.idiom_conflicts_path,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.promote.conflicts.artifact_written",
            artifact_path=str(paths.idiom_conflicts_path),
            artifact_format="json",
            conflict_count=conflict_snapshot_count,
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "conflicts_snapshot_written",
                "candidates_artifact": str(paths.idiom_candidates_path),
                "policies_artifact": str(paths.idiom_policies_path),
                "conflicts_artifact": str(paths.idiom_conflicts_path),
            },
            message="Idiom promotion stopped after conflict snapshot",
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.promote.completed",
            promoted_count=len(validation.promotion_entries),
            conflict_count=len(validation.conflicts),
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "promote_completed": True,
                "promoted_count": len(validation.promotion_entries),
            },
            message="Idiom preprocess stopped after promotion",
        )
    except StopRequested:
        raise
    except Exception as exc:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.promote.failed",
            severity="error",
            phase=phase,
            error=str(exc),
            message=f"Idiom promotion failed during {phase}: {exc}",
        )
        raise
    finally:
        conn.close()

    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
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


def _merge_usage_payloads(*payloads: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for payload in payloads:
        for key, value in payload.items():
            merged[key] = merged.get(key, 0) + value
    return merged
