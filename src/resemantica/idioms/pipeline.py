from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.db.idiom_repo import (
    find_exact_policy,
    get_checkpoint,
    insert_conflicts,
    list_candidates,
    list_candidates_for_promotion,
    list_candidates_for_review,
    list_candidates_for_translation,
    list_conflicts,
    list_policies,
    list_translation_votes,
    mark_candidate_conflict,
    mark_candidate_promoted,
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
from resemantica.orchestration.stop import StopToken, raise_if_stop_requested
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.utils import _build_llm_client, _write_json
from resemantica.utils import _emit as _emit_shared

_STAGE_NAME = "preprocess-idioms"


def _emit(run_id: str, release_id: str, event_type: str, **kwargs: object) -> None:
    _emit_shared(run_id, release_id, event_type, stage_name=_STAGE_NAME, **kwargs)


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


def _clean_llm_response(text: str) -> str:
    text = re.sub(
        r'^(?:Category|Translation|Term|Evidence|Output|Result)\s*:\s*',
        '', text, flags=re.IGNORECASE | re.MULTILINE
    ).strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else text


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
    stop_token: StopToken | None = None,
    event_callback: Callable[[str, dict[str, object]], None] | None = None,
) -> int:
    """Phase 2: Translate discovered idiom candidates using the Translator model.
    Two calls per candidate: idiom rendering + meaning translation.
    """
    def _notify(event_name: str, **payload: object) -> None:
        if event_callback is not None:
            event_callback(event_name, payload)

    pending = list_candidates_for_translation(conn, release_id=release_id)
    _notify(
        "translate.started",
        pending_count=len(pending),
        model_count=len(translator_model_names),
        message=f"Idiom translation started: {len(pending)} pending candidates",
    )
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

    current_model_name = ""
    current_candidate_id = ""
    current_vote_kind = ""
    try:
        for model_name in translator_model_names:
            current_model_name = model_name
            _notify(
                "translate.model_started",
                model_name=model_name,
                pending_count=len(pending),
                message=f"Idiom translation model {model_name} started: {len(pending)} candidates",
            )
            for candidate in pending:
                current_candidate_id = candidate.candidate_id
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
            _notify(
                "translate.model_completed",
                model_name=model_name,
                pending_count=len(pending),
                message=f"Idiom translation model {model_name} completed: {len(pending)} candidates",
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
    try:
        for candidate in pending:
            current_candidate_id = candidate.candidate_id
            current_vote_kind = "resolution"
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
            else:
                _notify(
                    "translate.unresolved",
                    severity="warning",
                    candidate_id=candidate.candidate_id,
                    vote_kind="rendering",
                    unresolved_count=unresolved_count,
                    message=(
                        "Idiom translation unresolved for candidate "
                        f"{candidate.candidate_id}: rendering vote prevented saving"
                    ),
                )
                logger.warning(
                    "Idiom translation unresolved for candidate {}: rendering vote prevented saving",
                    candidate.candidate_id,
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
        completed_chapters.append(active_chapter)
        raise_if_stop_requested(
            stop_token,
            checkpoint={"idiom_translate_completed_chapters": completed_chapters},
            message=f"Idiom translation stopped after chapter {active_chapter}",
        )
    _notify(
        "translate.completed",
        pending_count=len(pending),
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
        return {"status": "unresolved", "target_term": "", "model_name": ""}
    counts: dict[str, int] = {}
    for vote in ordered_votes:
        if vote.normalized_output:
            counts[vote.normalized_output] = counts.get(vote.normalized_output, 0) + 1
    if not counts:
        return {"status": "unresolved", "target_term": "", "model_name": ""}
    winning_normalized, winning_count = max(counts.items(), key=lambda item: item[1])
    if winning_count <= len(ordered_votes) // 2:
        return {"status": "unresolved", "target_term": "", "model_name": ""}
    status = "consensus" if winning_count == len(ordered_votes) else "majority"
    display_vote = next(vote for vote in ordered_votes if vote.normalized_output == winning_normalized)
    return {
        "status": status,
        "target_term": display_vote.cleaned_output,
        "model_name": display_vote.model_name,
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

    resume_stage = get_checkpoint(conn, release_id=release_id, run_id=run_id) if resume else None
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
                stop_token=stop_token,
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
        pending_candidates = list_candidates_for_promotion(conn, release_id=release_id)
        existing_policies = list_policies(conn, release_id=release_id)
        validation = validate_idiom_policy(
            candidates=pending_candidates,
            existing_policies=existing_policies,
            approval_run_id=run_id,
        )

        # Wipe old conflicts for all candidates — only current results appear
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
        if new_rendering and new_rendering != old_rendering:
            conn.execute(
                """
                UPDATE idiom_candidates
                SET preferred_rendering_en = ?,
                    translation_run_id = 'review',
                    candidate_status = 'translated',
                    validation_status = 'pending',
                    conflict_reason = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE candidate_id = ?
                """,
                (new_rendering, cid),
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
                meaning_en="",
                preferred_rendering_en=rendering,
                usage_notes=str(entry.get("usage_notes") or ""),
                first_seen_chapter=1,
                last_seen_chapter=1,
                appearance_count=1,
                evidence_snippet="",
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


def review_idiom_candidates(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "idioms")
    try:
        candidates = list_candidates_for_review(conn, release_id=release_id)
        votes = list_translation_votes(conn, release_id=release_id)
    finally:
        conn.close()

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
            "rendering": c.preferred_rendering_en,
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
    _write_json(paths.idiom_review_path, review_data)
    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.review.completed",
        entries_written=len(entries),
        review_path=str(paths.idiom_review_path),
    )
    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "entries_written": len(entries),
        "review_path": str(paths.idiom_review_path),
    }


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
    try:
        raise_if_stop_requested(
            stop_token,
            checkpoint={"promote_completed": False},
            message="Idiom promotion stopped before starting",
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
            pending_candidates = _apply_idiom_review_overrides(
                conn, release_id=release_id, review_data=review_data
            )
        else:
            pending_candidates = list_candidates_for_promotion(conn, release_id=release_id)

        existing_policies = list_policies(conn, release_id=release_id)
        validation = validate_idiom_policy(
            candidates=pending_candidates,
            existing_policies=existing_policies,
            approval_run_id=run_id,
        )

        # Wipe old conflicts for all candidates — only current results appear
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
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.promote.completed",
            promoted_count=len(validation.promotion_entries),
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
