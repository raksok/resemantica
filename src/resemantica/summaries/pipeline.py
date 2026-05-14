from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from loguru import logger

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.db.glossary_repo import list_locked_entries
from resemantica.db.sqlite import ensure_schema, open_connection
from resemantica.db.summary_repo import (
    ValidatedSummaryZhRecord,
    get_summary_checkpoint,
    get_validated_summary,
    is_non_story_chapter,
    list_validated_summaries,
    save_derived_summary,
    save_validated_summary,
    set_summary_checkpoint,
)
from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.llm.budget import PromptBudgetError
from resemantica.llm.client import (
    LLM_USAGE_PAYLOAD_FIELDS,
    LLMClient,
    capture_usage_snapshot,
    usage_payload_delta,
)
from resemantica.llm.prompts import load_prompt
from resemantica.orchestration.stop import StopToken, raise_if_stop_requested
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.summaries.derivation import (
    build_story_so_far,
    derive_english_summary,
    hash_locked_glossary,
    hash_validated_summary,
)
from resemantica.summaries.generator import generate_chapter_summary
from resemantica.summaries.validators import validate_chinese_summary_content
from resemantica.utils import _build_llm_client, _read_json, _write_json
from resemantica.utils import _emit as _emit_shared

_CHAPTER_FILE_RE = re.compile(r"chapter-(\d+)\.json$")
_STAGE_NAME = "preprocess-summaries"


@dataclass(slots=True)
class _PendingEnglishSummaryJob:
    result_index: int
    chapter_number: int
    locked_glossary: list[LockedGlossaryEntry]
    glossary_version_hash: str
    short_record: ValidatedSummaryZhRecord
    story_record: ValidatedSummaryZhRecord
    en_artifact: Path
    zh_usage_payload: dict[str, int]


def _emit(run_id: str, release_id: str, event_type: str, **kwargs: object) -> None:
    _emit_shared(run_id, release_id, event_type, stage_name=_STAGE_NAME, **kwargs)


def _sum_usage_payloads(*payloads: dict[str, int]) -> dict[str, int]:
    return {
        field: sum(int(payload.get(field, 0)) for payload in payloads)
        for field in LLM_USAGE_PAYLOAD_FIELDS
    }


def _collect_source_text(chapter_payload: dict[str, Any]) -> str:
    records_raw = chapter_payload.get("records", [])
    if not isinstance(records_raw, list):
        raise ValueError("Extracted chapter payload has invalid records field")
    records = sorted(
        records_raw,
        key=lambda row: (
            int(row.get("block_order", 0)),
            int(row.get("segment_order") or 0),
        ),
    )
    parts = [str(row.get("source_text_zh", "")) for row in records]
    return "\n".join(part for part in parts if part.strip())


def preprocess_summaries(
    *,
    release_id: str,
    run_id: str = "summaries",
    config: AppConfig | None = None,
    project_root: Path | None = None,
    llm_client: LLMClient | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    stop_token: StopToken | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    chapter_refs = list_extracted_chapters(
        paths,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
    )
    chapter_files = [ref.chapter_path for ref in chapter_refs]
    _exclude_patterns = config_obj.summaries.exclude_chapter_patterns
    _exclude_compiled = [re.compile(p) for p in _exclude_patterns] if _exclude_patterns else []
    if not chapter_files:
        raise FileNotFoundError(
            f"No extracted chapters found for release {release_id}: {paths.extracted_chapters_dir}"
        )
    _emit(run_id, release_id, f"{_STAGE_NAME}.started", total_chapters=len(chapter_files))

    client = _build_llm_client(config_obj, llm_client)
    prompt_structured = load_prompt("summary_zh_structured.txt")
    prompt_en = load_prompt("summary_en_derive.txt")
    prompt_validate = load_prompt("summary_zh_validate.txt")

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "glossary")
    ensure_schema(conn, "summaries")

    # Load per-chapter checkpoint for crash recovery
    zh_skip_until: int = 0
    en_skip_until: int = 0
    if resume:
        cp = get_summary_checkpoint(conn, release_id=release_id, run_id=run_id)
        if cp is not None:
            zh_skip_until = cp[0]
            en_skip_until = cp[1]
            logger.info(
                "Resuming summaries: zh_skip_until={}, en_skip_until={}",
                zh_skip_until, en_skip_until,
            )

    chapter_results: list[dict[str, Any]] = []
    pending_english_jobs: list[_PendingEnglishSummaryJob] = []

    try:
        for chapter_file in chapter_files:
            chapter_payload = _read_json(chapter_file)
            chapter_number = int(chapter_payload["chapter_number"])
            chapter_source_hash = str(chapter_payload["chapter_source_hash"])

            if zh_skip_until and chapter_number <= zh_skip_until:
                logger.debug("Chapter {}: already completed (zh phase), skipping", chapter_number)
                continue

            chapter_usage_before = capture_usage_snapshot(client)
            raise_if_stop_requested(
                stop_token,
                checkpoint={"chapter_artifacts": chapter_results},
                message="Summaries preprocess stopped before next chapter",
            )
            _emit(run_id, release_id, f"{_STAGE_NAME}.chapter_started", chapter_number=chapter_number)

            source_doc = str(chapter_payload.get("source_document_path", ""))
            if _exclude_compiled and any(p.search(source_doc) for p in _exclude_compiled):
                message = "Chapter {} skipped: source document {} matches exclude pattern"
                logger.info(message, chapter_number, source_doc)
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.chapter_skipped",
                    chapter_number=chapter_number,
                    message=message.format(chapter_number, source_doc),
                    reason="exclude_pattern",
                    **usage_payload_delta(client, chapter_usage_before),
                )
                chapter_results.append(
                    {
                        "chapter_number": chapter_number,
                        "chapter_source_hash": chapter_source_hash,
                        "status": "skipped",
                    }
                )
                raise_if_stop_requested(
                    stop_token,
                    checkpoint={"chapter_artifacts": chapter_results},
                    message=f"Summaries preprocess stopped after chapter {chapter_number}",
                )
                continue

            source_text_zh = _collect_source_text(chapter_payload)
            locked_glossary = list_locked_entries(conn, release_id=release_id)

            if is_non_story_chapter(conn, release_id=release_id, chapter_number=chapter_number):
                message = f"Chapter {chapter_number} skipped: non-story per existing draft flag"
                logger.info(message)
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.chapter_skipped",
                    chapter_number=chapter_number,
                    message=message,
                    reason="non_story_chapter",
                    **usage_payload_delta(client, chapter_usage_before),
                )
                chapter_results.append(
                    {
                        "chapter_number": chapter_number,
                        "chapter_source_hash": chapter_source_hash,
                        "status": "skipped",
                        "reason": "non_story_chapter",
                    }
                )
                raise_if_stop_requested(
                    stop_token,
                    checkpoint={"chapter_artifacts": chapter_results},
                    message=f"Summaries preprocess stopped after chapter {chapter_number}",
                )
                continue

            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.generation_started",
                chapter_number=chapter_number,
                message=f"Chinese summary generation started for chapter {chapter_number}",
                model_name=config_obj.models.analyst_name,
            )
            try:
                generated = generate_chapter_summary(
                    conn=conn,
                    release_id=release_id,
                    run_id=run_id,
                    chapter_number=chapter_number,
                    chapter_source_hash=chapter_source_hash,
                    source_document_path=source_doc,
                    source_text_zh=source_text_zh,
                    locked_glossary=locked_glossary,
                    llm_client=client,
                    model_name=config_obj.models.analyst_name,
                    prompt_template=prompt_structured.template,
                    prompt_version=prompt_structured.version,
                    config=config_obj,
                    cache_root=paths.release_root / "cache" / "llm",
                )
            except Exception as exc:
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.generation_failed",
                    chapter_number=chapter_number,
                    severity="error",
                    message=f"Chinese summary generation failed for chapter {chapter_number}: {exc}",
                    model_name=config_obj.models.analyst_name,
                    reason=str(exc),
                    **usage_payload_delta(client, chapter_usage_before),
                )
                raise
            if generated is None:
                if is_non_story_chapter(conn, release_id=release_id, chapter_number=chapter_number):
                    message = f"Chapter {chapter_number} skipped: non-story chapter flagged"
                    logger.info(message)
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.chapter_skipped",
                        chapter_number=chapter_number,
                        message=message,
                        reason="non_story_chapter",
                        **usage_payload_delta(client, chapter_usage_before),
                    )
                    chapter_results.append(
                        {
                            "chapter_number": chapter_number,
                            "chapter_source_hash": chapter_source_hash,
                            "status": "skipped",
                            "reason": "non_story_chapter",
                        }
                    )
                else:
                    message = f"Chapter {chapter_number} skipped: summary generation failed"
                    logger.warning(message)
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.generation_failed",
                        chapter_number=chapter_number,
                        severity="warning",
                        message=message,
                        model_name=config_obj.models.analyst_name,
                        reason="generation_returned_none",
                        **usage_payload_delta(client, chapter_usage_before),
                    )
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.chapter_skipped",
                        chapter_number=chapter_number,
                        severity="warning",
                        message=message,
                        reason="generation_failed",
                        **usage_payload_delta(client, chapter_usage_before),
                    )
                    chapter_results.append(
                        {
                            "chapter_number": chapter_number,
                            "chapter_source_hash": chapter_source_hash,
                            "status": "skipped",
                        }
                    )
                raise_if_stop_requested(
                    stop_token,
                    checkpoint={"chapter_artifacts": chapter_results},
                    message=f"Summaries preprocess stopped after chapter {chapter_number}",
                )
                continue
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.generation_completed",
                chapter_number=chapter_number,
                message=f"Chinese summary generation completed for chapter {chapter_number}",
                model_name=config_obj.models.analyst_name,
                status=generated.validation.status,
            )
            if generated.warnings:
                warning_message = (
                    f"Chapter {chapter_number} identity warning: "
                    + "; ".join(generated.warnings)
                )
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.chapter_identity_warning",
                    chapter_number=chapter_number,
                    severity="warning",
                    message=warning_message,
                    warnings=generated.warnings,
                )
            _emit(run_id, release_id, f"{_STAGE_NAME}.draft_generated", chapter_number=chapter_number)
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.validation_completed",
                chapter_number=chapter_number,
                status=generated.validation.status,
            )

            try:
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.llm_validation_started",
                    chapter_number=chapter_number,
                    message=f"LLM summary validation started for chapter {chapter_number}",
                    model_name=config_obj.models.analyst_name,
                )
                llm_validation = validate_chinese_summary_content(
                    llm_client=client,
                    model_name=config_obj.models.analyst_name,
                    prompt_template=prompt_validate.template,
                    source_text_zh=source_text_zh,
                    structured_summary=generated.structured_summary,
                    locked_glossary=locked_glossary,
                    chapter_identity_warnings=generated.warnings,
                    config=config_obj,
                )
            except PromptBudgetError:
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.llm_validation_failed",
                    chapter_number=chapter_number,
                    severity="warning",
                    message=f"LLM summary validation skipped for chapter {chapter_number}: prompt budget exceeded",
                    model_name=config_obj.models.analyst_name,
                    reason="prompt_budget_exceeded",
                    **usage_payload_delta(client, chapter_usage_before),
                )
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.chapter_skipped",
                    chapter_number=chapter_number,
                    reason="prompt_budget_exceeded",
                    **usage_payload_delta(client, chapter_usage_before),
                )
                chapter_results.append(
                    {
                        "chapter_number": chapter_number,
                        "chapter_source_hash": chapter_source_hash,
                        "status": "skipped",
                        "reason": "prompt_budget_exceeded",
                    }
                )
                raise_if_stop_requested(
                    stop_token,
                    checkpoint={"chapter_artifacts": chapter_results},
                    message=f"Summaries preprocess stopped after chapter {chapter_number}",
                )
                continue
            except Exception as exc:
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.llm_validation_failed",
                    chapter_number=chapter_number,
                    severity="error",
                    message=f"LLM summary validation failed for chapter {chapter_number}: {exc}",
                    model_name=config_obj.models.analyst_name,
                    reason=str(exc),
                    **usage_payload_delta(client, chapter_usage_before),
                )
                raise
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.llm_validation_completed",
                chapter_number=chapter_number,
                message=f"LLM summary validation completed for chapter {chapter_number}",
                model_name=config_obj.models.analyst_name,
                flag_count=len(llm_validation.flags),
                warning_count=len(llm_validation.warnings),
            )
            for flag in llm_validation.flags:
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.llm_validation_warning",
                    chapter_number=chapter_number,
                    severity="warning",
                    message=f"LLM summary validation warning for chapter {chapter_number}: {flag}",
                    flag=str(flag),
                )

            short_summaries = list_validated_summaries(
                conn,
                release_id=release_id,
                summary_type="chapter_summary_zh_short",
                max_chapter_number=chapter_number,
            )
            all_hashes = sorted(
                {r.derived_from_chapter_hash for r in short_summaries} | {chapter_source_hash}
            )
            composite_hash = sha256("|".join(all_hashes).encode()).hexdigest() if all_hashes else chapter_source_hash

            previous_story = get_validated_summary(
                conn,
                release_id=release_id,
                chapter_number=chapter_number - 1,
                summary_type="story_so_far_zh",
            )
            if previous_story is not None and short_summaries:
                last_short = short_summaries[-1]
                story_text = (
                    previous_story.content_zh.rstrip("\n")
                    + "\n"
                    + f"第{chapter_number}章：{last_short.content_zh.strip()}"
                )
            else:
                story_text = build_story_so_far(short_summaries=short_summaries)
            story_record = save_validated_summary(
                conn,
                release_id=release_id,
                chapter_number=chapter_number,
                summary_type="story_so_far_zh",
                content_zh=story_text,
                derived_from_chapter_hash=composite_hash,
                run_id=run_id,
                validation_status="approved",
            )

            glossary_version_hash = hash_locked_glossary(locked_glossary)
            zh_artifact = paths.summaries_dir / f"chapter-{chapter_number}-zh.json"
            en_artifact = paths.summaries_dir / f"chapter-{chapter_number}-en.json"
            _write_json(
                zh_artifact,
                {
                    "release_id": release_id,
                    "run_id": run_id,
                    "chapter_number": chapter_number,
                    "schema_version": 1,
                    "validated": {
                        "chapter_summary_zh_structured": generated.structured_record.to_json_dict(),
                        "chapter_summary_zh_short": generated.short_record.to_json_dict(),
                        "story_so_far_zh": story_record.to_json_dict(),
                    },
                    "llm_validation_flags": llm_validation.flags,
                    "llm_validation_warnings": llm_validation.warnings,
                    "warnings": generated.warnings,
                },
            )

            zh_usage_payload = usage_payload_delta(client, chapter_usage_before)
            result_index = len(chapter_results)
            chapter_results.append(
                {
                    "chapter_number": chapter_number,
                    "chapter_source_hash": chapter_source_hash,
                    "zh_artifact": str(zh_artifact),
                    "en_artifact": str(en_artifact),
                    "warnings": generated.warnings,
                }
            )
            pending_english_jobs.append(
                _PendingEnglishSummaryJob(
                    result_index=result_index,
                    chapter_number=chapter_number,
                    locked_glossary=locked_glossary,
                    glossary_version_hash=glossary_version_hash,
                    short_record=generated.short_record,
                    story_record=story_record,
                    en_artifact=en_artifact,
                    zh_usage_payload=zh_usage_payload,
                )
            )
            set_summary_checkpoint(conn, release_id=release_id, run_id=run_id, zh_last_chapter=chapter_number)
            raise_if_stop_requested(
                stop_token,
                checkpoint={"chapter_artifacts": chapter_results},
                message=f"Summaries preprocess stopped after chapter {chapter_number}",
            )

        for job in pending_english_jobs:
            if en_skip_until and job.chapter_number <= en_skip_until:
                logger.debug("Chapter {}: already completed (en phase), skipping", job.chapter_number)
                continue
            raise_if_stop_requested(
                stop_token,
                checkpoint={"chapter_artifacts": chapter_results},
                message="Summaries preprocess stopped before next English derivation",
            )
            en_usage_before = capture_usage_snapshot(client)
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.english_derivation_started",
                chapter_number=job.chapter_number,
                message=f"English summary derivation started for chapter {job.chapter_number}",
                model_name=config_obj.models.translator_name,
            )
            try:
                chapter_summary_en = derive_english_summary(
                    llm_client=client,
                    model_name=config_obj.models.translator_name,
                    prompt_template=prompt_en.template,
                    source_text_zh=job.short_record.content_zh,
                    locked_glossary=job.locked_glossary,
                )
            except Exception as exc:
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.english_derivation_failed",
                    chapter_number=job.chapter_number,
                    severity="error",
                    message=f"English summary derivation failed for chapter {job.chapter_number}: {exc}",
                    model_name=config_obj.models.translator_name,
                    reason=str(exc),
                    **usage_payload_delta(client, en_usage_before),
                )
                raise
            chapter_en_record = save_derived_summary(
                conn,
                release_id=release_id,
                chapter_number=job.chapter_number,
                summary_type="chapter_summary_en_short",
                content_en=chapter_summary_en,
                source_summary_id=job.short_record.summary_id,
                source_summary_hash=hash_validated_summary(job.short_record),
                glossary_version_hash=job.glossary_version_hash,
                model_name=config_obj.models.translator_name,
                prompt_version=prompt_en.version,
                run_id=run_id,
            )

            try:
                story_so_far_en = derive_english_summary(
                    llm_client=client,
                    model_name=config_obj.models.translator_name,
                    prompt_template=prompt_en.template,
                    source_text_zh=job.story_record.content_zh,
                    locked_glossary=job.locked_glossary,
                )
            except Exception as exc:
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.english_derivation_failed",
                    chapter_number=job.chapter_number,
                    severity="error",
                    message=f"English story-so-far derivation failed for chapter {job.chapter_number}: {exc}",
                    model_name=config_obj.models.translator_name,
                    reason=str(exc),
                    **usage_payload_delta(client, en_usage_before),
                )
                raise
            story_en_record = save_derived_summary(
                conn,
                release_id=release_id,
                chapter_number=job.chapter_number,
                summary_type="story_so_far_en",
                content_en=story_so_far_en,
                source_summary_id=job.story_record.summary_id,
                source_summary_hash=hash_validated_summary(job.story_record),
                glossary_version_hash=job.glossary_version_hash,
                model_name=config_obj.models.translator_name,
                prompt_version=prompt_en.version,
                run_id=run_id,
            )

            _write_json(
                job.en_artifact,
                {
                    "release_id": release_id,
                    "run_id": run_id,
                    "chapter_number": job.chapter_number,
                    "schema_version": 1,
                    "derived": {
                        "chapter_summary_en_short": chapter_en_record.to_json_dict(),
                        "story_so_far_en": story_en_record.to_json_dict(),
                    },
                },
            )
            chapter_results[job.result_index]["en_artifact"] = str(job.en_artifact)
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.english_derivation_completed",
                chapter_number=job.chapter_number,
                message=f"English summary derivation completed for chapter {job.chapter_number}",
                model_name=config_obj.models.translator_name,
                summary_count=2,
                **usage_payload_delta(client, en_usage_before),
            )
            set_summary_checkpoint(conn, release_id=release_id, run_id=run_id, en_last_chapter=job.chapter_number)
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.chapter_completed",
                chapter_number=job.chapter_number,
                summary_count=4,
                **_sum_usage_payloads(
                    job.zh_usage_payload,
                    usage_payload_delta(client, en_usage_before),
                ),
            )
            raise_if_stop_requested(
                stop_token,
                checkpoint={"chapter_artifacts": chapter_results},
                message=f"Summaries preprocess stopped after English derivation for chapter {job.chapter_number}",
            )
    finally:
        conn.close()

    processed_count = sum(
        1 for r in chapter_results if r.get("status") != "skipped"
    )
    skipped_count = sum(1 for r in chapter_results if r.get("status") == "skipped")
    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.completed",
        done=processed_count,
        skipped=skipped_count,
        failed=0,
        **capture_usage_snapshot(client).to_payload(),
    )
    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "chapters_processed": processed_count,
        "chapter_artifacts": chapter_results,
        **capture_usage_snapshot(client).to_payload(),
    }
