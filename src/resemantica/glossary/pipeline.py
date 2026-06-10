from __future__ import annotations

import csv
import json
import re
import sqlite3
import time
import unicodedata
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from loguru import logger

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.db.glossary_repo import (
    clear_alias_clusters_for_run,
    clear_candidate_translation_for_run,
    clear_discovery_chapter_state,
    count_translation_votes_by_model,
    find_exact_locked_entry,
    get_checkpoint,
    insert_conflicts,
    list_candidates,
    list_candidates_by_ids,
    list_candidates_for_promotion,
    list_candidates_for_review,
    list_candidates_for_translation,
    list_conflicts,
    list_existing_translation_vote_candidate_ids,
    list_locked_entries,
    list_translation_resume_candidate_ids,
    list_translation_vote_candidate_ids_for_run,
    list_translation_votes,
    list_translation_votes_for_review,
    mark_candidates_conflict,
    mark_candidates_promoted,
    promote_locked_entries,
    replace_candidates,
    save_candidate_translation,
    set_checkpoint,
    set_translation_vote_resolution,
    update_candidate_llm_fields,
    upsert_alias_clusters,
    upsert_discovered_candidates,
    upsert_translation_vote,
)
from resemantica.db.sqlite import ensure_schema, open_connection
from resemantica.glossary.critic import deduplicate_and_cluster
from resemantica.glossary.discovery import discover_candidates_from_extracted
from resemantica.glossary.evaluator import EvalResult, evaluate_candidate_batch
from resemantica.glossary.models import AliasCluster, GlossaryCandidate
from resemantica.glossary.validators import (
    apply_deterministic_filter,
    normalize_term,
    validate_candidates_for_promotion,
)
from resemantica.llm.client import LLMClient, capture_usage_snapshot, usage_payload_delta
from resemantica.llm.prompts import load_prompt
from resemantica.orchestration.stop import StopRequested, StopToken, raise_if_stop_requested
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.utils import _build_llm_client, _write_json
from resemantica.utils import _emit as _emit_shared

_STAGE_NAME = "preprocess-glossary"
_TRANSLATION_RESUME_FETCH_CHUNK_SIZE = 500


def _stable_json_hash(payload: object) -> str:
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _summary_seed_payload(summary_data: dict[str, Any] | None) -> dict[str, Any]:
    if not summary_data:
        return {}
    return {
        "characters_mentioned": summary_data.get("characters_mentioned", []),
        "new_terms": summary_data.get("new_terms", []),
        "setting": summary_data.get("setting", ""),
    }


def _discovery_settings_hash(config: AppConfig) -> str:
    return _stable_json_hash(
        {
            "schema_version": 1,
            "min_term_length": config.glossary.min_term_length,
            "max_term_length": config.glossary.max_term_length,
            "min_corpus_score": config.glossary.min_corpus_score,
            "eval_batch_size": config.glossary.eval_batch_size,
            "dedup_similarity_threshold": config.glossary.dedup_similarity_threshold,
        }
    )


def _chapter_source_hash(ref: Any) -> str:
    if ref.chapter_source_hash:
        return str(ref.chapter_source_hash)
    return sha256(ref.chapter_path.read_bytes()).hexdigest()


def _discover_stage_input_hash(
    *,
    chapter_refs: list[Any],
    chapter_summaries: dict[int, dict],
    skip_chapters: set[int],
    discovery_settings_hash: str,
    pruning_threshold: float | None,
) -> str:
    return _stable_json_hash(
        {
            "schema_version": 1,
            "chapters": [
                {
                    "chapter_number": ref.chapter_number,
                    "chapter_source_hash": _chapter_source_hash(ref),
                    "summary_seed": _summary_seed_payload(chapter_summaries.get(ref.chapter_number)),
                    "skip": ref.chapter_number in skip_chapters,
                }
                for ref in chapter_refs
            ],
            "discovery_settings_hash": discovery_settings_hash,
            "pruning_threshold": pruning_threshold,
        }
    )


def _eval_stage_input_hash(
    *,
    discover_input_hash: str,
    skip_llm_eval: bool,
    eval_batch_size: int | None,
    model_name: str,
    prompt_version: str | None,
) -> str:
    return _stable_json_hash(
        {
            "schema_version": 1,
            "discover_input_hash": discover_input_hash,
            "skip_llm_eval": skip_llm_eval,
            "eval_batch_size": eval_batch_size,
            "model_name": model_name,
            "prompt_version": prompt_version,
        }
    )


def _dedup_stage_input_hash(
    *,
    eval_input_hash: str,
    model_name: str,
    dedup_threshold: float | None,
) -> str:
    return _stable_json_hash(
        {
            "schema_version": 1,
            "eval_input_hash": eval_input_hash,
            "model_name": model_name,
            "dedup_threshold": dedup_threshold,
        }
    )


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
    eval_batch_size: int | None = None,
    skip_llm_eval: bool = False,
    resume: bool = False,
    force: bool = False,
    dedup_threshold: float | None = None,
    stop_token: StopToken | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    client = _build_llm_client(config_obj, llm_client)
    chapter_refs = list_extracted_chapters(
        paths,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
    )
    usage_before = capture_usage_snapshot(client)

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "glossary")

    # Load summary data and build skip/seed maps (if summaries have run)
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
            # Unwrap validation-failure wrapper: failed drafts store parsed
            # summary inside a "parsed_summary" key.
            content = raw.get("parsed_summary", raw)
            if isinstance(content, dict):
                chapter_summaries[ch] = content
    except Exception:
        pass  # Table may not exist if summaries haven't run yet

    glossary_discovery_settings_hash = _discovery_settings_hash(config_obj)
    discover_input_hash = _discover_stage_input_hash(
        chapter_refs=chapter_refs,
        chapter_summaries=chapter_summaries,
        skip_chapters=skip_chapters,
        discovery_settings_hash=glossary_discovery_settings_hash,
        pruning_threshold=pruning_threshold,
    )
    eval_prompt_version = None
    if not skip_llm_eval:
        eval_prompt_version = load_prompt("glossary_evaluate.txt").version
    eval_input_hash = _eval_stage_input_hash(
        discover_input_hash=discover_input_hash,
        skip_llm_eval=skip_llm_eval,
        eval_batch_size=eval_batch_size if eval_batch_size is not None else config_obj.glossary.eval_batch_size,
        model_name=config_obj.models.eval_name,
        prompt_version=eval_prompt_version,
    )
    dedup_input_hash = _dedup_stage_input_hash(
        eval_input_hash=eval_input_hash,
        model_name=config_obj.models.embedding_name,
        dedup_threshold=(
            dedup_threshold
            if dedup_threshold is not None
            else config_obj.glossary.dedup_similarity_threshold
        ),
    )

    resume_stage = None
    if force:
        with conn:
            clear_discovery_chapter_state(conn, release_id=release_id, run_id=run_id)
            clear_alias_clusters_for_run(conn, release_id=release_id, discovery_run_id=run_id)
            replace_candidates(conn, release_id=release_id, discovery_run_id=run_id, candidates=[])
            conn.execute(
                "DELETE FROM glossary_checkpoints WHERE release_id = ? AND run_id = ?",
                (release_id, run_id),
            )
    elif resume:
        checkpoint_stage = get_checkpoint(conn, release_id=release_id, run_id=run_id)
        expected_hash = {
            "filtered": discover_input_hash,
            "eval_completed": eval_input_hash,
            "dedup_completed": dedup_input_hash,
        }.get(checkpoint_stage or "")
        if expected_hash is not None:
            resume_stage = get_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                input_hash=expected_hash,
            )

    discovered: list[GlossaryCandidate] = []
    current_phase = "discovery"

    def _emit_discover_failed(exc: Exception) -> None:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.discover.failed",
            severity="error",
            phase=current_phase,
            error=str(exc),
            message=f"Glossary discovery failed during {current_phase}: {exc}",
        )

    def _emit_checkpoint_completed(
        *,
        checkpoint_stage: str,
        input_hash: str,
        skipped: bool,
        reason: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "message": (
                f"Glossary discovery checkpoint {'reused' if skipped else 'set'}: "
                f"{checkpoint_stage}"
            ),
            "checkpoint_stage": checkpoint_stage,
            "input_hash": input_hash,
            "candidate_count": len(discovered),
            "skipped": skipped,
        }
        if reason is not None:
            payload["reason"] = reason
        _emit(run_id, release_id, f"{_STAGE_NAME}.discover.checkpoint.completed", **payload)

    def _emit_discovery_event(
        event_name: str,
        chapter_number: int | None,
        payload: dict[str, object],
    ) -> None:
        nonlocal current_phase
        if event_name.startswith("prefilter."):
            current_phase = "prefilter"
        elif event_name.startswith("scoring."):
            current_phase = "scoring"
        else:
            current_phase = "extraction"
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.discover.{event_name}",
            chapter_number=chapter_number,
            **payload,
        )

    def _emit_eval_event(event_name: str, payload: dict[str, object]) -> None:
        legacy_payload = dict(payload)
        if event_name == "eval_batch_error":
            legacy_payload.setdefault("severity", "warning")
        _emit(run_id, release_id, f"{_STAGE_NAME}.eval.{event_name}", **legacy_payload)

        mapped = {
            "eval_batch_start": "batch_started",
            "eval_batch_success": "batch_completed",
            "eval_batch_cached": "batch_cached",
            "eval_batch_error": "batch_failed",
        }.get(event_name)
        if mapped is None:
            return
        scoped_payload = dict(payload)
        if mapped == "batch_failed":
            scoped_payload.setdefault("severity", "warning")
        _emit(run_id, release_id, f"{_STAGE_NAME}.discover.eval.{mapped}", **scoped_payload)

    try:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.started",
            total_chapters=len(chapter_refs),
        )

        # --- Stage 1-2: Discovery + Filter ---
        if resume_stage is None:
            current_phase = "extraction"
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.started",
                total_chapters=len(chapter_refs),
            )
            discovered = discover_candidates_from_extracted(
                release_id=release_id,
                discovery_run_id=run_id,
                chapter_refs=chapter_refs,
                skip_chapters=skip_chapters or None,
                chapter_summaries=chapter_summaries or None,
                event_callback=_emit_discovery_event,
                stop_token=stop_token,
                conn=conn,
                resume=resume and not force,
                discovery_settings_hash=glossary_discovery_settings_hash,
            )
            logger.info("Discovery: {} raw candidates from {} chapters", len(discovered), len(chapter_refs))

            current_phase = "filter"
            pre_filter_count = len(discovered)
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.filter.started",
                message=f"Deterministic filter started: {pre_filter_count} candidates",
                candidate_count=pre_filter_count,
                pre_filter_count=pre_filter_count,
                phase="filter",
            )
            discovered = apply_deterministic_filter(
                discovered,
                config=config_obj.glossary,
                min_score_override=pruning_threshold,
            )
            filtered_count_stage3 = sum(1 for c in discovered if c.candidate_status == "filtered")
            kept_after_filter = pre_filter_count - filtered_count_stage3
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.filter.completed",
                message=(
                    "Deterministic filter completed: "
                    f"{kept_after_filter} kept, {filtered_count_stage3} filtered"
                ),
                candidate_count=len(discovered),
                pre_filter_count=pre_filter_count,
                kept_count=kept_after_filter,
                filtered_count=filtered_count_stage3,
                phase="filter",
                skipped=False,
            )
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.filter_completed",
                message=f"Deterministic filter: {filtered_count_stage3} filtered from {pre_filter_count} candidates",
                pre_filter_count=pre_filter_count,
                filtered_count=filtered_count_stage3,
            )
            logger.info(
                "Filter stage: {} kept (of {}), {} filtered",
                kept_after_filter, pre_filter_count, filtered_count_stage3,
            )

            # Checkpoint after discovery + filter
            current_phase = "filter_persist"
            replace_candidates(conn, release_id=release_id, discovery_run_id=run_id, candidates=discovered)
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.filter.persisted",
                message=f"Deterministic filter persisted: {len(discovered)} candidates",
                candidate_count=len(discovered),
                pre_filter_count=pre_filter_count,
                kept_count=kept_after_filter,
                filtered_count=filtered_count_stage3,
                phase="filter",
                skipped=False,
            )
            logger.info("Filter persistence: {} candidates", len(discovered))
            set_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                stage_name="filtered",
                input_hash=discover_input_hash,
            )
            _emit_checkpoint_completed(
                checkpoint_stage="filtered",
                input_hash=discover_input_hash,
                skipped=False,
            )
            logger.info("Checkpoint set: filtered")
            resume_stage = "filtered"
        else:
            logger.info("Resuming from checkpoint stage: {}", resume_stage)
            discovered = [
                candidate
                for candidate in list_candidates(conn, release_id=release_id)
                if candidate.discovery_run_id == run_id
            ]
            if resume_stage in ("filtered", "eval_completed", "dedup_completed"):
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.discover.filter.completed",
                    message=f"Deterministic filter skipped: {resume_stage} checkpoint already exists",
                    candidate_count=len(discovered),
                    pre_filter_count=len(discovered),
                    kept_count=sum(1 for c in discovered if c.candidate_status != "filtered"),
                    filtered_count=sum(1 for c in discovered if c.candidate_status == "filtered"),
                    phase="filter",
                    skipped=True,
                    reason="resume_checkpoint",
                )
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.discover.filter.persisted",
                    message=f"Deterministic filter persistence skipped: {resume_stage} checkpoint already exists",
                    candidate_count=len(discovered),
                    phase="filter",
                    skipped=True,
                    reason="resume_checkpoint",
                )
                _emit_checkpoint_completed(
                    checkpoint_stage="filtered",
                    input_hash=discover_input_hash,
                    skipped=True,
                    reason="resume_checkpoint",
                )
                logger.info("Checkpoint reused: filtered")
            if resume_stage in ("eval_completed", "dedup_completed"):
                _emit_checkpoint_completed(
                    checkpoint_stage="eval_completed",
                    input_hash=eval_input_hash,
                    skipped=True,
                    reason="resume_checkpoint",
                )
                logger.info("Checkpoint reused: eval_completed")

        raise_if_stop_requested(stop_token)

        # --- Stage 4: LLM Batch Evaluation ---
        pending_eval = [
            c for c in discovered
            if c.candidate_status == "discovered" and c.llm_confidence is None
        ]
        eval_candidate_count = sum(1 for c in discovered if c.candidate_status == "discovered")
        current_phase = "eval"
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.discover.eval.started",
            message=f"Glossary LLM evaluation started: {len(pending_eval)} pending candidates",
            candidate_count=eval_candidate_count,
            pending_count=len(pending_eval),
            model_name=config_obj.models.eval_name,
            skipped=skip_llm_eval or resume_stage in ("eval_completed", "dedup_completed"),
            reason="skip_llm_eval" if skip_llm_eval else (
                "resume_checkpoint" if resume_stage in ("eval_completed", "dedup_completed") else None
            ),
        )
        if resume_stage in ("eval_completed", "dedup_completed"):
            reason = "resume_checkpoint"
            checkpoint_label = str(resume_stage)
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.eval.completed",
                message=f"Glossary LLM evaluation skipped: {checkpoint_label} checkpoint already exists",
                candidate_count=eval_candidate_count,
                pending_count=len(pending_eval),
                kept_count=0,
                rejected_count=0,
                model_name=config_obj.models.eval_name,
                skipped=True,
                reason=reason,
            )
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.eval.persisted",
                message=(
                    "Glossary LLM evaluation persistence skipped: "
                    f"{checkpoint_label} checkpoint already exists"
                ),
                candidate_count=len(discovered),
                skipped=True,
                reason=reason,
            )
        elif not skip_llm_eval:
            if pending_eval:
                eval_prompt = load_prompt("glossary_evaluate.txt")
                batch_sz = (
                    eval_batch_size if eval_batch_size is not None else config_obj.glossary.eval_batch_size
                )

                def _persist_eval_batch(results: list[EvalResult]) -> None:
                    for r in results:
                        update_candidate_llm_fields(
                            conn,
                            candidate_id=r.candidate_id,
                            llm_keep=r.keep,
                            llm_type=r.term_type,
                            llm_reason_code=r.reason_code,
                            llm_confidence=r.confidence,
                            candidate_status="discovered" if r.keep else "llm_rejected",
                        )
                    conn.commit()

                eval_results = evaluate_candidate_batch(
                    candidates=pending_eval,
                    llm_client=client,
                    model_name=config_obj.models.eval_name,
                    prompt_template=eval_prompt.template,
                    prompt_version=eval_prompt.version,
                    batch_size=batch_sz,
                    cache_root=paths.release_root / "cache" / "llm",
                    event_callback=_emit_eval_event,
                    persist_callback=_persist_eval_batch,
                )

                eval_map = {res.candidate_id: res for res in eval_results}
                for c in discovered:
                    if c.candidate_id in eval_map:
                        res = eval_map[c.candidate_id]
                        c.llm_keep = 1 if res.keep else 0
                        c.llm_type = res.term_type
                        c.llm_reason_code = res.reason_code
                        c.llm_confidence = res.confidence
                        if not res.keep:
                            c.candidate_status = "llm_rejected"

                llm_kept = sum(1 for c in pending_eval if c.candidate_status == "discovered")
                llm_rejected = sum(1 for c in pending_eval if c.candidate_status == "llm_rejected")
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.discover.eval.completed",
                    message=f"Glossary LLM evaluation completed: {llm_kept} kept, {llm_rejected} rejected",
                    candidate_count=eval_candidate_count,
                    pending_count=len(pending_eval),
                    kept_count=llm_kept,
                    rejected_count=llm_rejected,
                    model_name=config_obj.models.eval_name,
                    skipped=False,
                )
                logger.info("LLM eval: {} kept, {} rejected", llm_kept, llm_rejected)

                # Checkpoint after LLM eval
                current_phase = "eval_persist"
                replace_candidates(conn, release_id=release_id, discovery_run_id=run_id, candidates=discovered)
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.discover.eval.persisted",
                    message=f"Glossary LLM evaluation persisted: {len(discovered)} candidates",
                    candidate_count=len(discovered),
                    kept_count=llm_kept,
                    rejected_count=llm_rejected,
                    skipped=False,
                )
                logger.info("LLM eval persistence: {} candidates", len(discovered))
                set_checkpoint(
                    conn,
                    release_id=release_id,
                    run_id=run_id,
                    stage_name="eval_completed",
                    input_hash=eval_input_hash,
                )
                _emit_checkpoint_completed(
                    checkpoint_stage="eval_completed",
                    input_hash=eval_input_hash,
                    skipped=False,
                )
                logger.info("Checkpoint set: eval_completed")
                resume_stage = "eval_completed"
            else:
                reason = "no_pending_candidates"
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.discover.eval.completed",
                    message="Glossary LLM evaluation skipped: no pending candidates",
                    candidate_count=eval_candidate_count,
                    pending_count=0,
                    kept_count=0,
                    rejected_count=0,
                    model_name=config_obj.models.eval_name,
                    skipped=True,
                    reason=reason,
                )
                current_phase = "eval_persist"
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.discover.eval.persisted",
                    message="Glossary LLM evaluation persistence skipped: no pending candidates",
                    candidate_count=len(discovered),
                    skipped=True,
                    reason=reason,
                )
                set_checkpoint(
                    conn,
                    release_id=release_id,
                    run_id=run_id,
                    stage_name="eval_completed",
                    input_hash=eval_input_hash,
                )
                _emit_checkpoint_completed(
                    checkpoint_stage="eval_completed",
                    input_hash=eval_input_hash,
                    skipped=False,
                )
                logger.info("Checkpoint set: eval_completed")
                resume_stage = "eval_completed"
        else:
            reason = "skip_llm_eval"
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.eval.completed",
                message="Glossary LLM evaluation skipped: --skip-llm-eval",
                candidate_count=eval_candidate_count,
                pending_count=len(pending_eval),
                kept_count=0,
                rejected_count=0,
                model_name=config_obj.models.eval_name,
                skipped=True,
                reason=reason,
            )
            current_phase = "eval_persist"
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.eval.persisted",
                message="Glossary LLM evaluation persistence skipped: --skip-llm-eval",
                candidate_count=len(discovered),
                skipped=True,
                reason=reason,
            )

        raise_if_stop_requested(stop_token)

        # --- Stage 5: Embedding-based Dedup / Alias Clustering ---
        current_phase = "dedup"
        to_dedup = [c for c in discovered if c.candidate_status == "discovered"]
        clusters: list[AliasCluster] = []
        alias_merged = sum(1 for c in discovered if c.candidate_status == "alias_merged")
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.discover.dedup.started",
            message=f"Alias clustering started: {len(to_dedup)} candidates",
            candidate_count=len(to_dedup),
        )
        if resume_stage == "dedup_completed":
            logger.info("Resuming glossary: skipping dedup phase")
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.dedup.completed",
                message="Alias clustering skipped: dedup_completed checkpoint already exists",
                candidate_count=len(to_dedup),
                cluster_count=0,
                alias_merged_count=alias_merged,
                skipped=True,
                reason="resume_checkpoint",
            )
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.dedup.persisted",
                message="Alias clustering persistence skipped: dedup_completed checkpoint already exists",
                cluster_count=0,
                candidate_count=len(discovered),
                alias_merged_count=alias_merged,
                skipped=True,
                reason="resume_checkpoint",
            )
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.checkpoint.completed",
                message="Glossary discovery checkpoint reused: dedup_completed",
                checkpoint_stage="dedup_completed",
                input_hash=dedup_input_hash,
                skipped=True,
                reason="resume_checkpoint",
            )
        elif to_dedup:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.dedup_started",
                message=f"Alias clustering: {len(to_dedup)} candidates",
                candidate_count=len(to_dedup),
            )
            conn_tmp = open_connection(paths.db_path)
            existing_locked = list_locked_entries(conn_tmp, release_id=release_id)
            conn_tmp.close()

            sim_threshold = (
                dedup_threshold
                if dedup_threshold is not None
                else config_obj.glossary.dedup_similarity_threshold
            )

            _, clusters = deduplicate_and_cluster(
                candidates=to_dedup,
                model_name=config_obj.models.embedding_name,
                existing_entries=existing_locked,
                similarity_threshold=sim_threshold,
            )
            alias_merged = sum(1 for c in to_dedup if c.candidate_status == "alias_merged")
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.dedup.completed",
                message=f"Alias clustering complete: {len(clusters)} clusters, {alias_merged} aliases merged",
                candidate_count=len(to_dedup),
                cluster_count=len(clusters),
                alias_merged_count=alias_merged,
                skipped=False,
            )
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.dedup_completed",
                message=f"Clustering complete: {len(clusters)} clusters, {alias_merged} aliases merged",
                cluster_count=len(clusters),
                alias_merged_count=alias_merged,
            )
            logger.info("Dedup: {} clusters formed, {} aliases merged", len(clusters), alias_merged)

            current_phase = "dedup_persist"
            clear_alias_clusters_for_run(conn, release_id=release_id, discovery_run_id=run_id)
            if clusters:
                upsert_alias_clusters(
                    conn,
                    clusters=clusters,
                    release_id=release_id,
                    discovery_run_id=run_id,
                )
            replace_candidates(conn, release_id=release_id, discovery_run_id=run_id, candidates=discovered)
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.dedup.persisted",
                message=f"Alias clustering persisted: {len(clusters)} clusters, {len(discovered)} candidates",
                cluster_count=len(clusters),
                candidate_count=len(discovered),
                alias_merged_count=alias_merged,
            )
            logger.info(
                "Dedup persistence: {} clusters, {} candidates",
                len(clusters),
                len(discovered),
            )
            set_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                stage_name="dedup_completed",
                input_hash=dedup_input_hash,
            )
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.checkpoint.completed",
                message="Glossary discovery checkpoint set: dedup_completed",
                checkpoint_stage="dedup_completed",
                input_hash=dedup_input_hash,
                skipped=False,
            )
            logger.info("Checkpoint set: dedup_completed")
        elif resume_stage != "dedup_completed":
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.dedup.completed",
                message="Alias clustering skipped: no discovered candidates",
                candidate_count=0,
                cluster_count=0,
                alias_merged_count=0,
                skipped=True,
                reason="no_candidates",
            )
            current_phase = "dedup_persist"
            clear_alias_clusters_for_run(conn, release_id=release_id, discovery_run_id=run_id)
            replace_candidates(conn, release_id=release_id, discovery_run_id=run_id, candidates=discovered)
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.dedup.persisted",
                message=f"Alias clustering persisted: 0 clusters, {len(discovered)} candidates",
                cluster_count=0,
                candidate_count=len(discovered),
                alias_merged_count=0,
            )
            logger.info("Dedup persistence: 0 clusters, {} candidates", len(discovered))
            set_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                stage_name="dedup_completed",
                input_hash=dedup_input_hash,
            )
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.discover.checkpoint.completed",
                message="Glossary discovery checkpoint set: dedup_completed",
                checkpoint_stage="dedup_completed",
                input_hash=dedup_input_hash,
                skipped=False,
            )
            logger.info("Checkpoint set: dedup_completed")

        # --- Final snapshot write ---
        current_phase = "snapshot"
        snapshot_count = _write_candidate_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.glossary_candidates_path,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.discover.snapshot.artifact_written",
            message=f"Glossary candidate snapshot written: {paths.glossary_candidates_path}",
            artifact_path=str(paths.glossary_candidates_path),
            candidate_count=snapshot_count,
        )
        logger.info(
            "Candidate snapshot written: {} candidates to {}",
            snapshot_count,
            paths.glossary_candidates_path,
        )

    except StopRequested:
        raise
    except Exception as exc:
        _emit_discover_failed(exc)
        logger.opt(exception=True).error(
            "Glossary discovery failed during {}: {}",
            current_phase,
            exc,
        )
        raise
    finally:
        conn.close()

    filtered_count = sum(1 for c in discovered if c.candidate_status == "filtered")
    pruned_count = sum(1 for c in discovered if c.candidate_status == "pruned")
    llm_rejected_count = sum(1 for c in discovered if c.candidate_status == "llm_rejected")
    alias_merged_count = sum(1 for c in discovered if c.candidate_status == "alias_merged")

    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.discover.completed",
        discovered_count=len(discovered),
        filtered_count=filtered_count,
        llm_rejected_count=llm_rejected_count,
        alias_merged_count=alias_merged_count,
        pruned_count=pruned_count,
        **usage_payload_delta(client, usage_before),
    )
    raise_if_stop_requested(
        stop_token,
        checkpoint={"discover_completed": True, "candidates_written": len(discovered)},
        message="Glossary preprocess stopped after discovery",
    )

    logger.info(
        "Discover phase done: {} total (filtered={}, llm_rejected={}, alias_merged={}, pruned={})",
        len(discovered), filtered_count, llm_rejected_count, alias_merged_count, pruned_count,
    )

    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "candidates_written": len(discovered),
        "filtered_count": filtered_count,
        "llm_rejected_count": llm_rejected_count,
        "alias_merged_count": alias_merged_count,
        "pruned_count": pruned_count,
        "candidates_artifact": str(paths.glossary_candidates_path),
        **usage_payload_delta(client, usage_before),
    }


def _prompt_name_for_model(model_name: str) -> str:
    lowered = model_name.lower()
    if "gemma" in lowered:
        return "glossary_translate_gemma.txt"
    if "qwen" in lowered or "qwopus" in lowered:
        return "glossary_translate_qwen.txt"
    return "glossary_translate.txt"


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
            "Could not read prior glossary translation start event from {}",
            tracking_db_path,
        )
        return None
    if row is None:
        return None
    try:
        payload = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError:
        logger.debug("Ignoring malformed prior glossary translation payload")
        return None
    pending_count = payload.get("pending_count")
    return pending_count if isinstance(pending_count, int) else None


def translate_glossary_candidates(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    llm_client: LLMClient | None = None,
    force: bool = False,
    stop_token: StopToken | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    translator_names = config_obj.models.effective_preprocess_translator_names()
    loading_started_at = time.perf_counter()
    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.translate.loading_started",
        force=force,
        model_count=len(translator_names),
        db_path=str(paths.db_path),
        message="Glossary translation loading started",
    )
    logger.info(
        "Translation loading started: release={}, run={}, force={}, models={}, db={}",
        release_id,
        run_id,
        force,
        len(translator_names),
        paths.db_path,
    )
    client = _build_llm_client(config_obj, llm_client)
    usage_before = capture_usage_snapshot(client)

    # Load per-model prompts so each model gets the right instruction format
    model_prompts: dict[str, str] = {}
    model_prompt_versions: dict[str, str] = {}
    for model_name in translator_names:
        prompt_name = _prompt_name_for_model(model_name)
        pt = load_prompt(prompt_name)
        model_prompts[model_name] = pt.template
        model_prompt_versions[model_name] = pt.version

    db_prepare_started_at = time.perf_counter()
    conn = open_connection(paths.db_path)
    ensure_schema(conn, "glossary")
    db_prepare_seconds = time.perf_counter() - db_prepare_started_at
    logger.info(
        "Translation DB prepared in {:.3f}s: {}",
        db_prepare_seconds,
        paths.db_path,
    )
    try:
        pending_load_started_at = time.perf_counter()
        previous_pending_count: int | None = None
        resume_vote_model = ""
        resume_candidate_ids: list[str] = []
        vote_counts_by_model: dict[str, int] = {}
        load_strategy = "canonical_pending_scan"
        if force:
            pending = [
                candidate
                for candidate in list_candidates(conn, release_id=release_id)
                if candidate.llm_keep == 1 and candidate.candidate_status != "filtered"
            ]
            load_strategy = "force_full_scan"
        else:
            previous_pending_count = _previous_translate_pending_count(
                tracking_db_path=paths.release_root / "tracking.db",
                release_id=release_id,
                run_id=run_id,
            )
            vote_counts_by_model = count_translation_votes_by_model(
                conn,
                release_id=release_id,
                translation_run_id=run_id,
            )
            resume_vote_model = next(
                (
                    model_name
                    for model_name in translator_names
                    if previous_pending_count is not None
                    and vote_counts_by_model.get(model_name) == previous_pending_count
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
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.translate.loading_completed",
            force=force,
            pending_count=pending_count,
            candidate_count=pending_count,
            total_chapters=len(chapters_with_pending),
            model_count=len(translator_names),
            load_strategy=load_strategy,
            previous_pending_count=previous_pending_count,
            resume_vote_model=resume_vote_model,
            vote_counts_by_model=vote_counts_by_model,
            elapsed_seconds=round(loading_seconds, 3),
            db_prepare_seconds=round(db_prepare_seconds, 3),
            pending_load_seconds=round(pending_load_seconds, 3),
            message=f"Glossary translation loading completed: {pending_count} candidates",
        )
        logger.info(
            "Translation loading completed in {:.3f}s: {} candidates across {} chapters "
            "(strategy={}, db_prepare={:.3f}s, pending_load={:.3f}s, resume_vote_model={})",
            loading_seconds,
            pending_count,
            len(chapters_with_pending),
            load_strategy,
            db_prepare_seconds,
            pending_load_seconds,
            resume_vote_model or "none",
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.translate.started",
            total_chapters=len(chapters_with_pending),
            pending_count=pending_count,
            candidate_count=pending_count,
            model_count=len(translator_names),
        )
        logger.info(
            "Translation started: {} candidates pending across {} chapters",
            pending_count, len(chapters_with_pending),
        )
        current_model_name = ""
        current_candidate_id = ""
        try:
            for model_name in translator_names:
                current_model_name = model_name
                vote_lookup_started_at = time.perf_counter()
                existing_vote_candidate_ids = (
                    set()
                    if force
                    else list_existing_translation_vote_candidate_ids(
                        conn,
                        release_id=release_id,
                        translation_run_id=run_id,
                        model_name=model_name,
                    )
                )
                vote_lookup_seconds = time.perf_counter() - vote_lookup_started_at
                if load_strategy == "vote_resume":
                    model_pending_ids = [
                        candidate_id
                        for candidate_id in resume_candidate_ids
                        if candidate_id not in existing_vote_candidate_ids
                    ]
                    model_pending = []
                    model_candidate_count = len(model_pending_ids)
                else:
                    model_pending = [
                        candidate
                        for candidate in pending
                        if candidate.candidate_id not in existing_vote_candidate_ids
                    ]
                    model_pending_ids = []
                    model_candidate_count = len(model_pending)
                skipped_count = pending_count - model_candidate_count
                logger.info(
                    "Translation model {} resume lookup in {:.3f}s: {} existing votes, {} candidates pending",
                    model_name,
                    vote_lookup_seconds,
                    len(existing_vote_candidate_ids),
                    model_candidate_count,
                )
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.translate.model_started",
                    model_name=model_name,
                    pending_count=pending_count,
                    candidate_count=model_candidate_count,
                    skipped_count=skipped_count,
                    vote_lookup_seconds=round(vote_lookup_seconds, 3),
                    message=f"Glossary translation model {model_name} started: {model_candidate_count} candidates",
                )
                prompt_template = model_prompts.get(model_name, model_prompts.get(translator_names[0], ""))
                prompt_version = model_prompt_versions.get(model_name, "unknown")
                generated_count = 0
                if load_strategy == "vote_resume":
                    for candidate_id_batch in _chunks(
                        model_pending_ids,
                        _TRANSLATION_RESUME_FETCH_CHUNK_SIZE,
                    ):
                        candidate_batch = list_candidates_by_ids(
                            conn,
                            release_id=release_id,
                            candidate_ids=candidate_id_batch,
                        )
                        for candidate in candidate_batch:
                            current_candidate_id = candidate.candidate_id
                            translated = client.translate_glossary_candidate(
                                model_name=model_name,
                                prompt_template=prompt_template,
                                source_term=candidate.source_term,
                                category=candidate.category,
                                evidence_snippet=candidate.evidence_snippet,
                            )
                            upsert_translation_vote(
                                conn,
                                candidate_id=candidate.candidate_id,
                                release_id=release_id,
                                translation_run_id=run_id,
                                model_name=model_name,
                                prompt_version=prompt_version,
                                raw_output=translated,
                                cleaned_output=translated,
                                normalized_output=normalize_term(translated),
                            )
                            generated_count += 1
                else:
                    for candidate in model_pending:
                        current_candidate_id = candidate.candidate_id
                        translated = client.translate_glossary_candidate(
                            model_name=model_name,
                            prompt_template=prompt_template,
                            source_term=candidate.source_term,
                            category=candidate.category,
                            evidence_snippet=candidate.evidence_snippet,
                        )
                        upsert_translation_vote(
                            conn,
                            candidate_id=candidate.candidate_id,
                            release_id=release_id,
                            translation_run_id=run_id,
                            model_name=model_name,
                            prompt_version=prompt_version,
                            raw_output=translated,
                            cleaned_output=translated,
                            normalized_output=normalize_term(translated),
                        )
                        generated_count += 1
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.translate.model_completed",
                    model_name=model_name,
                    pending_count=pending_count,
                    candidate_count=generated_count,
                    skipped_count=skipped_count,
                    message=f"Glossary translation model {model_name} completed: {generated_count} candidates",
                )
                logger.info(
                    "Translation model {} complete: {} votes generated, {} existing votes skipped",
                    model_name,
                    generated_count,
                    skipped_count,
                )
        except Exception as exc:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.translate.failed",
                severity="error",
                model_name=current_model_name,
                candidate_id=current_candidate_id,
                phase="vote_generation",
                error=str(exc),
                message=(
                    "Glossary translation failed"
                    f" for model {current_model_name}, candidate {current_candidate_id}: {exc}"
                ),
            )
            logger.opt(exception=True).error(
                "Glossary translation failed for model {} candidate {}: {}",
                current_model_name,
                current_candidate_id,
                exc,
            )
            raise

        translated_count = 0
        unresolved_count = 0
        active_chapter: int | None = None
        chapter_usage_before = capture_usage_snapshot(client)
        chapter_candidate_count = 0
        chapter_translated_count = 0
        chapter_unresolved_count = 0
        completed_chapters: list[int] = []
        resolution_model_name = ""
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.translate.resolution.started",
            pending_count=pending_count,
            candidate_count=pending_count,
            model_count=len(translator_names),
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
                        candidate.normalized_source_term,
                        candidate.category,
                    )
                )
            else:
                resolution_candidates = pending
            for candidate in resolution_candidates:
                current_candidate_id = candidate.candidate_id
                chapter = candidate.first_seen_chapter
                if active_chapter != chapter:
                    if active_chapter is not None:
                        _emit(
                            run_id,
                            release_id,
                            f"{_STAGE_NAME}.translate.chapter_completed",
                            chapter_number=active_chapter,
                            candidate_count=chapter_candidate_count,
                            translated_count=chapter_translated_count,
                            unresolved_count=chapter_unresolved_count,
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
                    chapter_candidate_count = 0
                    chapter_translated_count = 0
                    chapter_unresolved_count = 0
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.translate.chapter_started",
                        chapter_number=chapter,
                    )
                chapter_candidate_count += 1
                result = _apply_candidate_vote_resolution(
                    conn,
                    release_id=release_id,
                    translation_run_id=run_id,
                    candidate=candidate,
                    translator_names=translator_names,
                    model_prompt_versions=model_prompt_versions,
                )
                resolution = result["resolution"]
                resolution_model_name = resolution.get("model_name", "")
                if result["translated"]:
                    translated_count += 1
                    chapter_translated_count += 1
                else:
                    unresolved_count += 1
                    chapter_unresolved_count += 1
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.translate.unresolved",
                        severity="warning",
                        candidate_id=candidate.candidate_id,
                        source_term=candidate.source_term,
                        chapter_number=candidate.first_seen_chapter,
                        unresolved_count=unresolved_count,
                        message=(
                            "Glossary translation unresolved for candidate "
                            f"{candidate.candidate_id}: no majority vote"
                        ),
                    )
                    logger.warning(
                        "Translation unresolved for candidate {} (no majority vote)",
                        candidate.candidate_id,
                    )
        except Exception as exc:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.translate.failed",
                severity="error",
                model_name=resolution_model_name,
                candidate_id=current_candidate_id,
                phase="resolution",
                error=str(exc),
                message=(
                    "Glossary translation failed"
                    f" while resolving candidate {current_candidate_id}: {exc}"
                ),
            )
            logger.opt(exception=True).error(
                "Glossary translation failed while resolving candidate {}: {}",
                current_candidate_id,
                exc,
            )
            raise
        if active_chapter is not None:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.translate.chapter_completed",
                chapter_number=active_chapter,
                candidate_count=chapter_candidate_count,
                translated_count=chapter_translated_count,
                unresolved_count=chapter_unresolved_count,
                **usage_payload_delta(client, chapter_usage_before),
            )
            completed_chapters.append(active_chapter)
            raise_if_stop_requested(
                stop_token,
                checkpoint={"translate_completed_chapters": completed_chapters},
                message=f"Glossary translation stopped after chapter {active_chapter}",
            )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.translate.resolution.completed",
            pending_count=pending_count,
            candidate_count=pending_count,
            translated_count=translated_count,
            unresolved_count=unresolved_count,
        )
        logger.info(
            "Translation resolution complete: {} translated, {} unresolved",
            translated_count,
            unresolved_count,
        )

        snapshot_count = _write_candidate_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.glossary_candidates_path,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.translate.snapshot.artifact_written",
            artifact_path=str(paths.glossary_candidates_path),
            candidate_count=snapshot_count,
        )
        logger.info(
            "Translation candidate snapshot written: {} candidates -> {}",
            snapshot_count,
            paths.glossary_candidates_path,
        )
    finally:
        conn.close()

    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.translate.completed",
        translated_count=translated_count,
        unresolved_count=unresolved_count,
        **usage_payload_delta(client, usage_before),
    )
    logger.info(
        "Translation complete: {} translated, {} unresolved",
        translated_count, unresolved_count,
    )

    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "translated_count": translated_count,
        "unresolved_count": unresolved_count,
        "candidates_artifact": str(paths.glossary_candidates_path),
        **usage_payload_delta(client, usage_before),
    }


def _empty_vote_resolution() -> dict[str, str]:
    return {
        "status": "unresolved",
        "target_term": "",
        "normalized_target_term": "",
        "model_name": "",
        "prompt_version": "",
    }


def _ascii_fold(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )


def _strip_leading_article(value: str) -> str:
    return re.sub(r"^(?:the|a|an)\s+", "", value, count=1)


def _has_leading_article(value: str) -> bool:
    return bool(re.match(r"^(?:the|a|an)\s+", value.strip(), flags=re.IGNORECASE))


def _base_resolution_key(value: str) -> str:
    normalized = normalize_term(_ascii_fold(value))
    normalized = _strip_leading_article(normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _dynasty_family(source_term: str) -> tuple[str, tuple[str, ...]] | None:
    if "大骊" in source_term:
        return "Great Li", ("great li", "da li", "dalí", "dali")
    if "大隋" in source_term:
        return "Great Sui", ("great sui", "da sui", "dasiu")
    return None


def _dynasty_resolution_key(value: str, source_term: str) -> str:
    key = _base_resolution_key(value)
    family = _dynasty_family(source_term)
    if family is None:
        return key
    _preferred, variants = family
    for variant in sorted(variants, key=len, reverse=True):
        key = re.sub(rf"\b{re.escape(variant)}\b", "__dynasty__", key)
    return key


def _preferred_dynasty_display(value: str, source_term: str) -> str:
    family = _dynasty_family(source_term)
    if family is None:
        return value
    preferred, variants = family
    result = value
    for variant in sorted(variants, key=len, reverse=True):
        result = re.sub(rf"\b{re.escape(variant)}\b", preferred, result, flags=re.IGNORECASE)
    return result


def _has_tao_dao_disagreement(votes: list[Any]) -> bool:
    has_tao = False
    has_dao = False
    for vote in votes:
        key = _base_resolution_key(str(vote.cleaned_output or vote.normalized_output or ""))
        has_tao = has_tao or bool(re.search(r"\btao\w*\b", key))
        has_dao = has_dao or bool(re.search(r"\bdao\w*\b", key))
    return has_tao and has_dao


def _resolve_translation_votes(
    votes: list[Any],
    model_order: list[str],
    *,
    source_term: str = "",
) -> dict[str, str]:
    votes_by_model = {vote.model_name: vote for vote in votes}
    ordered_votes = [votes_by_model[name] for name in model_order if name in votes_by_model]
    if not ordered_votes:
        return _empty_vote_resolution()
    if _has_tao_dao_disagreement(ordered_votes):
        return _empty_vote_resolution()

    votes_by_key: dict[str, list[Any]] = {}
    for vote in ordered_votes:
        cleaned_output = str(vote.cleaned_output or "").strip()
        if cleaned_output:
            key = _dynasty_resolution_key(cleaned_output, source_term)
            if key:
                votes_by_key.setdefault(key, []).append(vote)
    if not votes_by_key:
        return _empty_vote_resolution()

    winning_key, winning_votes = max(
        votes_by_key.items(),
        key=lambda item: (
            len(item[1]),
            -min(model_order.index(vote.model_name) for vote in item[1] if vote.model_name in model_order),
        ),
    )
    winning_count = len(winning_votes)
    if winning_count <= len(ordered_votes) // 2:
        return _empty_vote_resolution()

    status = "consensus" if winning_count == len(ordered_votes) else "majority"
    surfaces: dict[str, int] = {}
    for vote in winning_votes:
        surfaces[str(vote.cleaned_output).strip()] = surfaces.get(str(vote.cleaned_output).strip(), 0) + 1
    display_surface = max(
        surfaces,
        key=lambda surface: (
            surfaces[surface],
            0 if _has_leading_article(surface) else 1,
            -next(
                index
                for index, vote in enumerate(ordered_votes)
                if str(vote.cleaned_output).strip() == surface
            ),
        ),
    )
    display_vote = next(
        vote
        for vote in ordered_votes
        if str(vote.cleaned_output).strip() == display_surface and vote in winning_votes
    )
    target_term = _preferred_dynasty_display(display_surface, source_term)
    return {
        "status": status,
        "target_term": target_term,
        "normalized_target_term": normalize_term(target_term) or winning_key,
        "model_name": display_vote.model_name,
        "prompt_version": display_vote.prompt_version,
    }


def _apply_candidate_vote_resolution(
    conn: Any,
    *,
    release_id: str,
    translation_run_id: str,
    candidate: GlossaryCandidate,
    translator_names: list[str],
    model_prompt_versions: dict[str, str] | None = None,
    clear_stale_translation: bool = False,
) -> dict[str, Any]:
    votes = list_translation_votes(
        conn,
        release_id=release_id,
        candidate_id=candidate.candidate_id,
    )
    votes = [vote for vote in votes if vote.translation_run_id == translation_run_id]
    resolution = _resolve_translation_votes(
        votes,
        translator_names,
        source_term=candidate.source_term,
    )
    set_translation_vote_resolution(
        conn,
        candidate_id=candidate.candidate_id,
        translation_run_id=translation_run_id,
        resolution_status=resolution["status"],
    )
    if resolution["target_term"]:
        prompt_versions = model_prompt_versions or {}
        save_candidate_translation(
            conn,
            candidate_id=candidate.candidate_id,
            translation_run_id=translation_run_id,
            target_term=resolution["target_term"],
            normalized_target_term=resolution["normalized_target_term"],
            translator_model_name=resolution["model_name"],
            translator_prompt_version=(
                resolution.get("prompt_version")
                or prompt_versions.get(resolution.get("model_name", ""), "unknown")
            ),
        )
        return {
            "resolution": resolution,
            "translated": True,
            "unresolved": False,
            "cleared_stale": False,
        }

    cleared_stale = False
    if (
        clear_stale_translation
        and candidate.translation_run_id == translation_run_id
        and (candidate.candidate_translation_en or "").strip()
    ):
        clear_candidate_translation_for_run(
            conn,
            candidate_id=candidate.candidate_id,
            translation_run_id=translation_run_id,
        )
        cleared_stale = True
    return {
        "resolution": resolution,
        "translated": False,
        "unresolved": True,
        "cleared_stale": cleared_stale,
    }


def _load_vote_resolution_candidates(
    conn: Any,
    *,
    release_id: str,
    translation_run_id: str,
) -> list[GlossaryCandidate]:
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
            candidate.normalized_source_term,
            candidate.category,
        )
    )
    return candidates


def _existing_vote_alternatives_for_prompt(votes: list[Any], model_order: list[str]) -> str:
    votes_by_model = {vote.model_name: vote for vote in votes}
    ordered_votes = [votes_by_model[name] for name in model_order if name in votes_by_model]
    ordered_votes.extend(
        vote
        for vote in votes
        if vote.model_name not in model_order
    )
    alternatives: list[str] = []
    seen: set[str] = set()
    for vote in ordered_votes:
        cleaned = str(vote.cleaned_output or "").strip()
        if not cleaned:
            continue
        key = normalize_term(cleaned)
        if key in seen:
            continue
        seen.add(key)
        alternatives.append(f"- {cleaned}")
    return "\n".join(alternatives) if alternatives else "- None"


def _load_glossary_fill_candidates(
    conn: Any,
    *,
    release_id: str,
    translation_run_id: str,
    translator_names: list[str],
) -> list[GlossaryCandidate]:
    candidates = _load_vote_resolution_candidates(
        conn,
        release_id=release_id,
        translation_run_id=translation_run_id,
    )
    fill_candidates: list[GlossaryCandidate] = []
    for candidate in candidates:
        if candidate.candidate_status == "promoted":
            continue
        if (candidate.candidate_translation_en or "").strip():
            continue
        votes = [
            vote
            for vote in list_translation_votes(
                conn,
                release_id=release_id,
                candidate_id=candidate.candidate_id,
            )
            if vote.translation_run_id == translation_run_id
        ]
        resolution = _resolve_translation_votes(
            votes,
            translator_names,
            source_term=candidate.source_term,
        )
        if not resolution["target_term"]:
            fill_candidates.append(candidate)
    return fill_candidates


def fill_glossary_translation_votes(
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
    prompt = load_prompt("glossary_fill.txt")
    phase = "start"
    conn = open_connection(paths.db_path)
    ensure_schema(conn, "glossary")
    try:
        raise_if_stop_requested(
            stop_token,
            checkpoint={"fill_completed": False},
            message="Glossary filler stopped before starting",
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.fill.started",
            translation_run_id=run_id,
            filler_model_count=len(filler_model_names),
            force=force,
            message="Glossary filler started",
        )

        phase = "load_candidates"
        candidates = _load_glossary_fill_candidates(
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
            message=f"Glossary filler loaded {len(candidates)} unresolved candidates",
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint={"phase": "candidates_loaded", "candidate_count": len(candidates)},
            message="Glossary filler stopped after loading candidates",
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
                    message=f"Glossary filler model {model_name} started: {len(model_pending)} candidates",
                )
                generated_count = 0
                for candidate in model_pending:
                    current_candidate_id = candidate.candidate_id
                    votes = [
                        vote
                        for vote in list_translation_votes(
                            conn,
                            release_id=release_id,
                            candidate_id=candidate.candidate_id,
                        )
                        if vote.translation_run_id == run_id
                    ]
                    translated = client.translate_glossary_fill_candidate(
                        model_name=model_name,
                        prompt_template=prompt.template,
                        source_term=candidate.source_term,
                        category=candidate.category,
                        evidence_snippet=candidate.evidence_snippet,
                        existing_alternatives=_existing_vote_alternatives_for_prompt(
                            votes,
                            translator_names,
                        ),
                    )
                    upsert_translation_vote(
                        conn,
                        candidate_id=candidate.candidate_id,
                        release_id=release_id,
                        translation_run_id=run_id,
                        model_name=model_name,
                        prompt_version=prompt.version,
                        raw_output=translated,
                        cleaned_output=translated,
                        normalized_output=normalize_term(translated),
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
                    message=f"Glossary filler model {model_name} completed: {generated_count} votes",
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
                error=str(exc),
                message=(
                    "Glossary filler failed"
                    f" for model {current_model_name}, candidate {current_candidate_id}: {exc}"
                ),
            )
            raise

        phase = "resolve_votes"
        translated_count = 0
        unresolved_count = 0
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.fill.resolution.started",
            candidate_count=len(candidates),
            filler_vote_count=filler_vote_count,
            skipped_vote_count=skipped_vote_count,
        )
        for candidate in candidates:
            result = _apply_candidate_vote_resolution(
                conn,
                release_id=release_id,
                translation_run_id=run_id,
                candidate=candidate,
                translator_names=model_order,
            )
            if result["translated"]:
                translated_count += 1
            else:
                unresolved_count += 1
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.fill.unresolved",
                    severity="warning",
                    candidate_id=candidate.candidate_id,
                    source_term=candidate.source_term,
                    chapter_number=candidate.first_seen_chapter,
                    unresolved_count=unresolved_count,
                    message=(
                        "Glossary filler unresolved for candidate "
                        f"{candidate.candidate_id}: no majority vote"
                    ),
                )
            raise_if_stop_requested(
                stop_token,
                checkpoint={
                    "phase": "resolve_votes",
                    "translated_count": translated_count,
                    "unresolved_count": unresolved_count,
                },
                message="Glossary filler stopped while resolving candidates",
            )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.fill.resolution.completed",
            candidate_count=len(candidates),
            translated_count=translated_count,
            unresolved_count=unresolved_count,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.fill.completed",
            translation_run_id=run_id,
            candidate_count=len(candidates),
            filler_vote_count=filler_vote_count,
            skipped_vote_count=skipped_vote_count,
            translated_count=translated_count,
            unresolved_count=unresolved_count,
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
                message=f"Glossary filler failed during {phase}: {exc}",
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
        **usage_payload_delta(client, usage_before),
    }


def resolve_glossary_translation_votes(
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
    ensure_schema(conn, "glossary")
    try:
        raise_if_stop_requested(
            stop_token,
            checkpoint={"resolve_completed": False},
            message="Glossary vote resolution stopped before starting",
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.resolve.started",
            translation_run_id=run_id,
            model_count=len(translator_names),
            message="Glossary saved-vote resolution started",
        )
        logger.info(
            "Saved-vote resolution started: release={}, run={}, models={}, db={}",
            release_id,
            run_id,
            len(translator_names),
            paths.db_path,
        )

        phase = "load_candidates"
        candidates = _load_vote_resolution_candidates(
            conn,
            release_id=release_id,
            translation_run_id=run_id,
        )
        candidates = [candidate for candidate in candidates if candidate.candidate_status != "promoted"]
        logger.info(
            "Saved-vote resolution loaded {} candidates from run {}",
            len(candidates),
            run_id,
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint={"phase": "candidates_loaded", "candidate_count": len(candidates)},
            message="Glossary vote resolution stopped after loading candidates",
        )

        phase = "resolve_votes"
        translated_count = 0
        unresolved_count = 0
        stale_cleared_count = 0
        for candidate in candidates:
            result = _apply_candidate_vote_resolution(
                conn,
                release_id=release_id,
                translation_run_id=run_id,
                candidate=candidate,
                translator_names=translator_names,
                clear_stale_translation=True,
            )
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
                    severity="warning",
                    candidate_id=candidate.candidate_id,
                    source_term=candidate.source_term,
                    chapter_number=candidate.first_seen_chapter,
                    unresolved_count=unresolved_count,
                    message=(
                        "Glossary saved-vote resolution unresolved for candidate "
                        f"{candidate.candidate_id}: no majority vote"
                    ),
                )
                logger.warning(
                    "Saved-vote resolution unresolved for candidate {} ({})",
                    candidate.candidate_id,
                    candidate.source_term,
                )
            raise_if_stop_requested(
                stop_token,
                checkpoint={
                    "phase": "resolve_votes",
                    "translated_count": translated_count,
                    "unresolved_count": unresolved_count,
                },
                message="Glossary vote resolution stopped while resolving candidates",
            )

        phase = "write_candidates_snapshot"
        snapshot_count = _write_candidate_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.glossary_candidates_path,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.resolve.snapshot.artifact_written",
            artifact_path=str(paths.glossary_candidates_path),
            artifact_format="json",
            candidate_count=snapshot_count,
        )
        logger.info(
            "Saved-vote resolution candidate snapshot written: {} candidates -> {}",
            snapshot_count,
            paths.glossary_candidates_path,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.resolve.completed",
            translation_run_id=run_id,
            candidate_count=len(candidates),
            translated_count=translated_count,
            unresolved_count=unresolved_count,
            stale_cleared_count=stale_cleared_count,
            candidates_artifact=str(paths.glossary_candidates_path),
        )
        logger.info(
            "Saved-vote resolution complete: {} translated, {} unresolved, {} stale translations cleared",
            translated_count,
            unresolved_count,
            stale_cleared_count,
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
            message=f"Glossary saved-vote resolution failed during {phase}: {exc}",
        )
        logger.opt(exception=True).error(
            "Saved-vote resolution failed during {}: {}",
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
        "stale_cleared_count": stale_cleared_count,
        "candidates_artifact": str(paths.glossary_candidates_path),
    }


def promote_glossary_candidates(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    review_file_path: Path | None = None,
    force: bool = False,
    stop_token: StopToken | None = None,
    llm_usage_payload: dict[str, int] | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "glossary")
    phase = "start"
    try:
        raise_if_stop_requested(
            stop_token,
            checkpoint={"promote_completed": False},
            message="Glossary promotion stopped before starting",
        )
        _emit(run_id, release_id, f"{_STAGE_NAME}.promote.started")
        logger.info("Promotion phase started")

        if review_file_path is not None:
            phase = "review_file"
            if not review_file_path.exists():
                raise FileNotFoundError(f"Review file not found: {review_file_path}")
            review_data = _read_review_data(review_file_path)
            raise_if_stop_requested(
                stop_token,
                checkpoint={"phase": "review_file_loaded"},
                message="Glossary promotion stopped after reading review file",
            )
            promotable_candidates = _apply_review_overrides(
                conn, release_id=release_id, review_data=review_data
            )
            raise_if_stop_requested(
                stop_token,
                checkpoint={"phase": "review_overrides_applied"},
                message="Glossary promotion stopped after applying review overrides",
            )
        else:
            phase = "load_candidates"
            promotable_candidates = (
                [
                    candidate
                    for candidate in list_candidates(conn, release_id=release_id)
                    if candidate.llm_keep == 1 and candidate.candidate_translation_en
                ]
                if force
                else list_candidates_for_promotion(conn, release_id=release_id)
            )
            raise_if_stop_requested(
                stop_token,
                checkpoint={"phase": "candidates_loaded"},
                message="Glossary promotion stopped after loading candidates",
            )

        phase = "validation"
        raise_if_stop_requested(
            stop_token,
            checkpoint={"phase": "validation_pending"},
            message="Glossary promotion stopped before validation",
        )
        existing_entries = list_locked_entries(conn, release_id=release_id)
        promotion_entries, conflicts = validate_candidates_for_promotion(
            candidates=promotable_candidates,
            existing_entries=existing_entries,
            approval_run_id=run_id,
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "validation_completed",
                "candidate_count": len(promotable_candidates),
                "conflict_count": len(conflicts),
            },
            message="Glossary promotion stopped after validation",
        )

        reasons_by_candidate: dict[str, list[str]] = {}
        for conflict in conflicts:
            reasons_by_candidate.setdefault(conflict.candidate_id, []).append(conflict.conflict_reason)

        promotable_without_conflicts = [
            entry
            for entry in promotion_entries
            if entry.source_candidate_id not in reasons_by_candidate
        ]
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "promotion_pending",
                "promoted_count": len(promotable_without_conflicts),
                "conflict_count": len(conflicts),
            },
            message="Glossary promotion stopped before writing locked glossary",
        )

        # All DB writes in a single transaction — batch via executemany
        with conn:
            if promotable_candidates:
                _all_ids = [c.candidate_id for c in promotable_candidates]
                _placeholders = ",".join("?" for _ in _all_ids)
                conn.execute(
                    f"DELETE FROM glossary_conflicts "
                    f"WHERE candidate_id IN ({_placeholders}) AND release_id = ?",
                    [*_all_ids, release_id],
                )
            insert_conflicts(conn, conflicts=conflicts)
            mark_candidates_conflict(
                conn,
                conflicts=[(cid, " | ".join(reasons)) for cid, reasons in reasons_by_candidate.items()],
            )
            promote_locked_entries(conn, entries=promotable_without_conflicts)
            mark_candidates_promoted(
                conn,
                candidate_ids=[entry.source_candidate_id for entry in promotable_without_conflicts],
            )
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "promotion_written",
                "promoted_count": len(promotable_without_conflicts),
                "conflict_count": len(conflicts),
            },
            message="Glossary promotion stopped after writing locked glossary",
        )

        phase = "write_candidates_snapshot"
        raise_if_stop_requested(
            stop_token,
            checkpoint={"phase": "candidates_snapshot_pending"},
            message="Glossary promotion stopped before candidate snapshot",
        )
        candidate_snapshot_count = _write_candidate_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.glossary_candidates_path,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.promote.candidates.artifact_written",
            artifact_path=str(paths.glossary_candidates_path),
            artifact_format="json",
            candidate_count=candidate_snapshot_count,
        )
        phase = "write_conflicts_snapshot"
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "candidates_snapshot_written",
                "candidates_artifact": str(paths.glossary_candidates_path),
            },
            message="Glossary promotion stopped after candidate snapshot",
        )
        conflict_snapshot_count = _write_conflict_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.glossary_conflicts_path,
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.promote.conflicts.artifact_written",
            artifact_path=str(paths.glossary_conflicts_path),
            artifact_format="json",
            conflict_count=conflict_snapshot_count,
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "conflicts_snapshot_written",
                "candidates_artifact": str(paths.glossary_candidates_path),
                "conflicts_artifact": str(paths.glossary_conflicts_path),
            },
            message="Glossary promotion stopped after conflict snapshot",
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.promote.completed",
            promoted_count=len(promotable_without_conflicts),
            conflict_count=len(conflicts),
            **(llm_usage_payload or {}),
        )
        logger.info(
            "Promotion complete: {} entries promoted, {} conflicts",
            len(promotable_without_conflicts), len(conflicts),
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
            message=f"Glossary promotion failed during {phase}: {exc}",
        )
        raise
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
    from dataclasses import replace as _dataclass_replace
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
            all_candidates[cid] = _dataclass_replace(
                candidate,
                candidate_translation_en=new_translation,
                normalized_target_term=normalized,
                candidate_status="translated",
                validation_status="pending",
                conflict_reason=None,
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


_CSV_HEADER = ["action", "source_term", "category", "translation",
                "candidate_id", "evidence_snippet", "alternatives"]


def _write_review_csv(path: Path, entries: list[dict[str, Any]]) -> None:
    rows: list[list[str]] = [_CSV_HEADER]
    for entry in entries:
        snippet = (entry.get("evidence_snippet") or "")
        snippet = snippet.replace("\n", " ").replace("\r", " ")
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        alts = [a.get("translation", "") for a in (entry.get("alternatives") or [])]
        rows.append([
            entry.get("action") or "keep",
            entry.get("source_term") or "",
            entry.get("category") or "",
            entry.get("translation") or "",
            entry.get("candidate_id") or "",
            snippet,
            "|".join(alts),
        ])
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerows(rows)


def _read_review_csv(path: Path) -> dict[str, Any]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter="\t")
        raw_rows = list(reader)
    if not raw_rows:
        raise ValueError("Review CSV is empty")
    header = raw_rows[0]
    if header != _CSV_HEADER:
        raise ValueError(
            f"Review CSV has invalid header. Expected: {_CSV_HEADER!r}, got: {header!r}"
        )
    entries: list[dict[str, Any]] = []
    for row in raw_rows[1:]:
        if len(row) < len(_CSV_HEADER):
            row += [""] * (len(_CSV_HEADER) - len(row))
        action = row[0].strip().lower() if row[0].strip() else "keep"
        entries.append({
            "candidate_id": row[4].strip() or None,
            "source_term": row[1].strip(),
            "category": row[2].strip(),
            "translation": row[3].strip(),
            "action": action,
            "evidence_snippet": row[5].strip(),
        })
    return {
        "review_schema_version": 1,
        "entries": entries,
    }


def _read_review_data(review_file_path: Path) -> dict[str, Any]:
    if review_file_path.suffix.lower() == ".csv":
        return _read_review_csv(review_file_path)
    review_data: dict[str, Any] = json.loads(review_file_path.read_text(encoding="utf-8"))
    if review_data.get("review_schema_version") != 1:
        raise ValueError(
            f"Unsupported review schema version: {review_data.get('review_schema_version')}"
        )
    return review_data


def review_glossary_candidates(
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
            message="Glossary review stopped before starting",
        )
        _emit(run_id, release_id, f"{_STAGE_NAME}.review.started")
        conn = open_connection(paths.db_path)
        ensure_schema(conn, "glossary")
        try:
            candidates = list_candidates_for_review(conn, release_id=release_id)
            votes = list_translation_votes_for_review(conn, release_id=release_id)
        finally:
            conn.close()
        raise_if_stop_requested(
            stop_token,
            checkpoint={"phase": "candidates_loaded", "candidate_count": len(candidates)},
            message="Glossary review stopped after loading candidates",
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
            candidate_votes.sort(key=lambda vote: model_order.get(vote.model_name, len(model_order)))

        entries = [
            {
                "candidate_id": c.candidate_id,
                "source_term": c.source_term,
                "category": c.category,
                "translation": c.candidate_translation_en or "",
                "evidence_snippet": c.evidence_snippet,
                "alternatives": [
                    {
                        "model_name": vote.model_name,
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
                "Edit 'translation' to override a term's English rendering. "
                "Set 'action' to 'delete' to remove an entry. "
                "Add new entries with 'action': 'add' "
                "(omit candidate_id, provide source_term, category, translation, evidence_snippet)."
            ),
            "entries": entries,
        }
        review_csv_path = paths.glossary_review_path.with_suffix(".csv")
        phase = "write_review_json"
        raise_if_stop_requested(
            stop_token,
            checkpoint={"phase": "review_json_pending", "entries_written": len(entries)},
            message="Glossary review stopped before writing review JSON",
        )
        _write_json(paths.glossary_review_path, review_data)
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.review.json.artifact_written",
            artifact_path=str(paths.glossary_review_path),
            artifact_format="json",
            entries_written=len(entries),
        )
        phase = "write_review_csv"
        raise_if_stop_requested(
            stop_token,
            checkpoint={
                "phase": "review_json_written",
                "entries_written": len(entries),
                "review_json_path": str(paths.glossary_review_path),
            },
            message="Glossary review stopped after writing review JSON",
        )
        _write_review_csv(review_csv_path, entries)
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
                "review_json_path": str(paths.glossary_review_path),
                "review_csv_path": str(review_csv_path),
            },
            message="Glossary review stopped after writing review CSV",
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.review.completed",
            entries_written=len(entries),
            review_path=str(paths.glossary_review_path),
            review_json_path=str(paths.glossary_review_path),
            review_csv_path=str(review_csv_path),
        )
        logger.info("Review file written: {} entries -> {}", len(entries), paths.glossary_review_path)
        return {
            "status": "success",
            "release_id": release_id,
            "run_id": run_id,
            "entries_written": len(entries),
            "review_path": str(paths.glossary_review_path),
            "review_json_path": str(paths.glossary_review_path),
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
            message=f"Glossary review failed during {phase}: {exc}",
        )
        raise


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
