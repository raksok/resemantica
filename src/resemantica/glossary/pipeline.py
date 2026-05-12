from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.db.glossary_repo import (
    find_exact_locked_entry,
    get_checkpoint,
    insert_conflicts,
    list_candidates,
    list_candidates_for_promotion,
    list_candidates_for_review,
    list_candidates_for_translation,
    list_conflicts,
    list_locked_entries,
    list_translation_votes,
    mark_candidate_conflict,
    mark_candidate_promoted,
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
from resemantica.orchestration.stop import StopToken, raise_if_stop_requested
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.utils import _build_llm_client, _write_json
from resemantica.utils import _emit as _emit_shared

_STAGE_NAME = "preprocess-glossary"


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
    eval_batch_size: int | None = None,
    skip_llm_eval: bool = False,
    resume: bool = False,
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

    # Query non-story chapters from summaries data (if summaries have run)
    skip_chapters: set[int] = set()
    try:
        cursor = conn.execute(
            "SELECT chapter_number FROM summary_drafts "
            "WHERE release_id = ? AND summary_type = 'chapter_summary_zh_structured' AND is_story_chapter = 0",
            (release_id,),
        )
        for row in cursor.fetchall():
            skip_chapters.add(int(row[0]))
    except Exception:
        pass  # Table may not exist if summaries haven't run yet

    resume_stage = get_checkpoint(conn, release_id=release_id, run_id=run_id) if resume else None

    try:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.started",
            total_chapters=len(chapter_refs),
        )

        # --- Stage 1-2: Discovery + Filter ---
        if resume_stage is None:
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
                event_callback=lambda event_name, chapter_number, payload: _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.discover.{event_name}",
                    chapter_number=chapter_number,
                    **payload,
                ),
                stop_token=stop_token,
            )
            logger.info("Discovery: {} raw candidates from {} chapters", len(discovered), len(chapter_refs))

            pre_filter_count = len(discovered)
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
            replace_candidates(conn, release_id=release_id, discovery_run_id=run_id, candidates=discovered)
            set_checkpoint(conn, release_id=release_id, run_id=run_id, stage_name="filtered")
            resume_stage = "filtered"
        else:
            logger.info("Resuming from checkpoint stage: {}", resume_stage)
            discovered = list_candidates(conn, release_id=release_id)

        raise_if_stop_requested(stop_token)

        # --- Stage 4: LLM Batch Evaluation ---
        if not skip_llm_eval:
            pending_eval = [c for c in discovered if c.candidate_status == "discovered" and c.llm_confidence is None]
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
                        )

                eval_results = evaluate_candidate_batch(
                    candidates=pending_eval,
                    llm_client=client,
                    model_name=config_obj.models.eval_name,
                    prompt_template=eval_prompt.template,
                    prompt_version=eval_prompt.version,
                    batch_size=batch_sz,
                    cache_root=paths.release_root / "cache" / "llm",
                    event_callback=lambda event, payload: _emit(
                        run_id, release_id, f"{_STAGE_NAME}.eval.{event}", **payload
                    ),
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
                logger.info("LLM eval: {} kept, {} rejected", llm_kept, llm_rejected)

                # Checkpoint after LLM eval
                replace_candidates(conn, release_id=release_id, discovery_run_id=run_id, candidates=discovered)
                set_checkpoint(conn, release_id=release_id, run_id=run_id, stage_name="eval_started")

        raise_if_stop_requested(stop_token)

        # --- Stage 5: Embedding-based Dedup / Alias Clustering ---
        to_dedup = [c for c in discovered if c.candidate_status == "discovered"]
        clusters: list[AliasCluster] = []
        if to_dedup:
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
                f"{_STAGE_NAME}.discover.dedup_completed",
                message=f"Clustering complete: {len(clusters)} clusters, {alias_merged} aliases merged",
                cluster_count=len(clusters),
                alias_merged_count=alias_merged,
            )
            logger.info("Dedup: {} clusters formed, {} aliases merged", len(clusters), alias_merged)

            if clusters:
                upsert_alias_clusters(
                    conn,
                    clusters=clusters,
                    release_id=release_id,
                    discovery_run_id=run_id,
                )
            set_checkpoint(conn, release_id=release_id, run_id=run_id, stage_name="dedup_completed")

        # --- Final snapshot write ---
        _write_candidate_snapshot(
            conn,
            release_id=release_id,
            output_path=paths.glossary_candidates_path,
        )

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
    translator_names = config_obj.models.effective_preprocess_translator_names()

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
        logger.info(
            "Translation started: {} candidates pending across {} chapters",
            len(pending), len(chapters_with_pending),
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
        for model_name in translator_names:
            for candidate in pending:
                translated = client.translate_glossary_candidate(
                    model_name=model_name,
                    prompt_template=prompt.template,
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
                    prompt_version=prompt.version,
                    raw_output=translated,
                    cleaned_output=translated,
                    normalized_output=normalize_term(translated),
                )

        translated_count = 0
        unresolved_count = 0
        for candidate in pending:
            votes = list_translation_votes(
                conn,
                release_id=release_id,
                candidate_id=candidate.candidate_id,
            )
            votes = [vote for vote in votes if vote.translation_run_id == run_id]
            resolution = _resolve_translation_votes(votes, translator_names)
            set_translation_vote_resolution(
                conn,
                candidate_id=candidate.candidate_id,
                translation_run_id=run_id,
                resolution_status=resolution["status"],
            )
            if resolution["target_term"]:
                save_candidate_translation(
                    conn,
                    candidate_id=candidate.candidate_id,
                    translation_run_id=run_id,
                    target_term=resolution["target_term"],
                    normalized_target_term=resolution["normalized_target_term"],
                    translator_model_name=resolution["model_name"],
                    translator_prompt_version=prompt.version,
                )
                translated_count += 1
            else:
                unresolved_count += 1
                logger.warning(
                    "Translation unresolved for candidate {} (no majority vote)",
                    candidate.candidate_id,
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


def _resolve_translation_votes(votes: list[Any], model_order: list[str]) -> dict[str, str]:
    votes_by_model = {vote.model_name: vote for vote in votes}
    ordered_votes = [votes_by_model[name] for name in model_order if name in votes_by_model]
    if not ordered_votes:
        return {
            "status": "unresolved",
            "target_term": "",
            "normalized_target_term": "",
            "model_name": "",
        }

    counts: dict[str, int] = {}
    for vote in ordered_votes:
        if vote.normalized_output:
            counts[vote.normalized_output] = counts.get(vote.normalized_output, 0) + 1
    if not counts:
        return {
            "status": "unresolved",
            "target_term": "",
            "normalized_target_term": "",
            "model_name": "",
        }

    winning_normalized, winning_count = max(counts.items(), key=lambda item: item[1])
    if winning_count <= len(ordered_votes) // 2:
        return {
            "status": "unresolved",
            "target_term": "",
            "normalized_target_term": "",
            "model_name": "",
        }

    status = "consensus" if winning_count == len(ordered_votes) else "majority"
    display_vote = next(vote for vote in ordered_votes if vote.normalized_output == winning_normalized)
    return {
        "status": status,
        "target_term": display_vote.cleaned_output,
        "normalized_target_term": winning_normalized,
        "model_name": display_vote.model_name,
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
        logger.info("Promotion phase started")

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
    _write_json(paths.glossary_review_path, review_data)
    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.review.completed",
        entries_written=len(entries),
        review_path=str(paths.glossary_review_path),
    )
    logger.info("Review file written: {} entries -> {}", len(entries), paths.glossary_review_path)
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
