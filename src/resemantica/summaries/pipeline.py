from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from loguru import logger

from resemantica.chapters.manifest import ChapterRef, list_extracted_chapters
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
from resemantica.llm.prompts import PromptTemplate, load_prompt
from resemantica.orchestration.stop import StopToken, raise_if_stop_requested
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.summaries.derivation import (
    build_story_so_far,
    compact_story_so_far,
    derive_english_summary,
    hash_locked_glossary,
    hash_validated_summary,
)
from resemantica.summaries.generator import GeneratedChapterSummary, generate_chapter_summary
from resemantica.summaries.validators import (
    SummaryContentValidationResult,
    validate_chinese_summary_content,
)
from resemantica.utils import _build_llm_client, _read_json, _write_json
from resemantica.utils import _emit as _emit_shared

_STAGE_NAME = "preprocess-summaries"
_CHECKPOINTABLE_SKIP_REASONS = {"exclude_pattern", "non_story_chapter"}
_FAILED_DRAFT_STATUSES = {"failed"}


@dataclass(slots=True)
class _ChinesePhaseResult:
    chapter_number: int
    chapter_source_hash: str
    status: str
    reason: str | None = None
    warnings: list[str] | None = None
    llm_validation_flags: list[str] | None = None
    llm_validation_warnings: list[str] | None = None
    structured_record: ValidatedSummaryZhRecord | None = None
    short_record: ValidatedSummaryZhRecord | None = None
    zh_usage_payload: dict[str, int] | None = None


@dataclass(slots=True)
class _EnglishPhaseJob:
    chapter_number: int
    locked_glossary: list[LockedGlossaryEntry]
    glossary_version_hash: str
    short_record: ValidatedSummaryZhRecord
    compact_story_record: ValidatedSummaryZhRecord
    en_artifact: Path
    zh_usage_payload: dict[str, int]


@dataclass(slots=True)
class _EnglishPhaseResult:
    chapter_number: int
    chapter_record: dict[str, object]
    story_record: dict[str, object]
    en_artifact: Path
    en_usage_payload: dict[str, int]


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


def _is_excluded(ref: ChapterRef, exclude_patterns: list[re.Pattern[str]]) -> bool:
    source_doc = ref.source_document_path or ""
    return bool(exclude_patterns and any(pattern.search(source_doc) for pattern in exclude_patterns))


def _checkpoint_can_advance(result: _ChinesePhaseResult) -> bool:
    return result.status == "completed" or (
        result.status == "skipped" and result.reason in _CHECKPOINTABLE_SKIP_REASONS
    )


def _latest_summary_draft_failure(
    conn: Any,
    *,
    release_id: str,
    chapter_number: int,
) -> tuple[str, list[str], list[str], list[str]]:
    row = conn.execute(
        """
        SELECT validation_status, content_json
        FROM summary_drafts
        WHERE release_id = ?
          AND chapter_number = ?
          AND summary_type = 'chapter_summary_zh_structured'
        LIMIT 1
        """,
        (release_id, chapter_number),
    ).fetchone()
    if row is None or str(row["validation_status"]) not in _FAILED_DRAFT_STATUSES:
        return "generation_failed", [], [], []
    try:
        content = _read_json_from_text(str(row["content_json"]))
    except ValueError:
        return "generation_failed", [], [], []
    category = str(content.get("failure_category") or "generation_failed")
    errors = content.get("validation_errors", [])
    flags = content.get("llm_validation_flags", [])
    warnings = content.get("llm_validation_warnings", [])
    return (
        category,
        [str(error) for error in errors] if isinstance(errors, list) else [],
        [str(flag) for flag in flags] if isinstance(flags, list) else [],
        [str(warning) for warning in warnings] if isinstance(warnings, list) else [],
    )


def _read_json_from_text(text: str) -> dict[str, Any]:
    import json

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed


def _advance_chinese_checkpoint(
    *,
    completed: dict[int, _ChinesePhaseResult],
    current: int,
    ordered_numbers: list[int],
) -> int:
    advanced = current
    for number in ordered_numbers:
        if number <= advanced:
            continue
        result = completed.get(number)
        if result is None or not _checkpoint_can_advance(result):
            break
        advanced = number
    return advanced


def _load_validated_artifact_notes(path: Path) -> tuple[list[str], list[str], list[str]]:
    if not path.exists():
        return [], [], []
    try:
        payload = _read_json(path)
    except (OSError, ValueError):
        return [], [], []
    flags = payload.get("llm_validation_flags", [])
    llm_warnings = payload.get("llm_validation_warnings", [])
    warnings = payload.get("warnings", [])
    return (
        [str(item) for item in flags] if isinstance(flags, list) else [],
        [str(item) for item in llm_warnings] if isinstance(llm_warnings, list) else [],
        [str(item) for item in warnings] if isinstance(warnings, list) else [],
    )


def _run_chinese_phase(
    *,
    ref: ChapterRef,
    db_path: Path,
    release_id: str,
    run_id: str,
    config: AppConfig,
    llm_client: LLMClient,
    prompt_structured: PromptTemplate,
    prompt_validate: PromptTemplate,
    cache_root: Path,
    exclude_patterns: list[re.Pattern[str]],
) -> _ChinesePhaseResult:
    chapter_payload = _read_json(ref.chapter_path)
    chapter_number = int(chapter_payload["chapter_number"])
    chapter_source_hash = str(chapter_payload["chapter_source_hash"])
    source_doc = str(chapter_payload.get("source_document_path", ""))
    usage_before = capture_usage_snapshot(llm_client)
    _emit(run_id, release_id, f"{_STAGE_NAME}.chapter_started", chapter_number=chapter_number)

    if _is_excluded(ref, exclude_patterns):
        message = f"Chapter {chapter_number} skipped: source document {source_doc} matches exclude pattern"
        logger.info(message)
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.chapter_skipped",
            chapter_number=chapter_number,
            message=message,
            reason="exclude_pattern",
            **usage_payload_delta(llm_client, usage_before),
        )
        return _ChinesePhaseResult(
            chapter_number=chapter_number,
            chapter_source_hash=chapter_source_hash,
            status="skipped",
            reason="exclude_pattern",
            zh_usage_payload=usage_payload_delta(llm_client, usage_before),
        )

    conn = open_connection(db_path)
    ensure_schema(conn, "glossary")
    ensure_schema(conn, "summaries")
    try:
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
                **usage_payload_delta(llm_client, usage_before),
            )
            return _ChinesePhaseResult(
                chapter_number=chapter_number,
                chapter_source_hash=chapter_source_hash,
                status="skipped",
                reason="non_story_chapter",
                zh_usage_payload=usage_payload_delta(llm_client, usage_before),
            )

        source_text_zh = _collect_source_text(chapter_payload)
        locked_glossary = list_locked_entries(conn, release_id=release_id)
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.generation_started",
            chapter_number=chapter_number,
            message=f"Chinese summary generation started for chapter {chapter_number}",
            model_name=config.models.analyst_name,
        )

        def content_validator(
            *,
            structured_summary: dict[str, object],
            chapter_identity_warnings: list[str],
            attempt_number: int,
        ) -> SummaryContentValidationResult:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.llm_validation_started",
                chapter_number=chapter_number,
                message=f"LLM summary validation started for chapter {chapter_number}",
                model_name=config.models.analyst_name,
                attempt_number=attempt_number,
            )
            try:
                return validate_chinese_summary_content(
                    llm_client=llm_client,
                    model_name=config.models.analyst_name,
                    prompt_template=prompt_validate.template,
                    source_text_zh=source_text_zh,
                    structured_summary=structured_summary,
                    locked_glossary=locked_glossary,
                    chapter_identity_warnings=chapter_identity_warnings,
                    config=config,
                )
            except PromptBudgetError:
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.llm_validation_failed",
                    chapter_number=chapter_number,
                    severity="warning",
                    message=(
                        f"LLM summary validation skipped for chapter {chapter_number}: "
                        "prompt budget exceeded"
                    ),
                    model_name=config.models.analyst_name,
                    reason="prompt_budget_exceeded",
                    attempt_number=attempt_number,
                    **usage_payload_delta(llm_client, usage_before),
                )
                raise
            except Exception as exc:
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.llm_validation_failed",
                    chapter_number=chapter_number,
                    severity="error",
                    message=f"LLM summary validation failed for chapter {chapter_number}: {exc}",
                    model_name=config.models.analyst_name,
                    reason=str(exc),
                    attempt_number=attempt_number,
                    **usage_payload_delta(llm_client, usage_before),
                )
                raise

        def content_validation_event_handler(
            *,
            result: SummaryContentValidationResult,
            attempt_number: int,
            action: str,
        ) -> None:
            _emit_llm_validation_events(
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                model_name=config.models.analyst_name,
                flags=result.flags,
                warnings=result.warnings,
                attempt_number=attempt_number,
                action=action,
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
                llm_client=llm_client,
                model_name=config.models.analyst_name,
                prompt_template=prompt_structured.template,
                prompt_version=prompt_structured.version,
                config=config,
                cache_root=cache_root,
                content_validator=content_validator,
                content_validation_event_handler=content_validation_event_handler,
            )
        except PromptBudgetError:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.chapter_skipped",
                chapter_number=chapter_number,
                reason="prompt_budget_exceeded",
                **usage_payload_delta(llm_client, usage_before),
            )
            return _ChinesePhaseResult(
                chapter_number=chapter_number,
                chapter_source_hash=chapter_source_hash,
                status="skipped",
                reason="prompt_budget_exceeded",
                zh_usage_payload=usage_payload_delta(llm_client, usage_before),
            )
        except Exception as exc:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.generation_failed",
                chapter_number=chapter_number,
                severity="error",
                message=f"Chinese summary generation failed for chapter {chapter_number}: {exc}",
                model_name=config.models.analyst_name,
                reason=str(exc),
                **usage_payload_delta(llm_client, usage_before),
            )
            raise

        if generated is None:
            return _handle_empty_generation(
                conn=conn,
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                chapter_source_hash=chapter_source_hash,
                llm_client=llm_client,
                usage_before=usage_before,
                model_name=config.models.analyst_name,
            )

        _emit_generated_summary_events(
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            generated=generated,
            model_name=config.models.analyst_name,
        )
        return _ChinesePhaseResult(
            chapter_number=chapter_number,
            chapter_source_hash=chapter_source_hash,
            status="completed",
            warnings=generated.warnings,
            llm_validation_flags=generated.llm_validation_flags,
            llm_validation_warnings=generated.llm_validation_warnings,
            structured_record=generated.structured_record,
            short_record=generated.short_record,
            zh_usage_payload=usage_payload_delta(llm_client, usage_before),
        )
    finally:
        conn.close()


def _handle_empty_generation(
    *,
    conn: Any,
    release_id: str,
    run_id: str,
    chapter_number: int,
    chapter_source_hash: str,
    llm_client: LLMClient,
    usage_before: Any,
    model_name: str,
) -> _ChinesePhaseResult:
    llm_validation_flags: list[str] = []
    llm_validation_warnings: list[str] = []
    if is_non_story_chapter(conn, release_id=release_id, chapter_number=chapter_number):
        message = f"Chapter {chapter_number} skipped: non-story chapter flagged"
        logger.info(message)
        reason = "non_story_chapter"
        severity = None
        status = "skipped"
    else:
        failure_category, errors, llm_validation_flags, llm_validation_warnings = _latest_summary_draft_failure(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
        )
        message = f"Chapter {chapter_number} failed: summary generation exhausted"
        logger.warning(message)
        reason = failure_category
        severity = "error"
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.generation_failed",
            chapter_number=chapter_number,
            severity="error",
            message=message,
            model_name=model_name,
            reason=reason,
            errors=errors,
            llm_validation_flags=llm_validation_flags,
            **usage_payload_delta(llm_client, usage_before),
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.chapter_failed",
            chapter_number=chapter_number,
            severity="error",
            message=message,
            reason=reason,
            errors=errors,
            llm_validation_flags=llm_validation_flags,
            **usage_payload_delta(llm_client, usage_before),
        )
        status = "failed"
    payload = {
        "chapter_number": chapter_number,
        "message": message,
        "reason": reason,
        **usage_payload_delta(llm_client, usage_before),
    }
    if severity is not None:
        payload["severity"] = severity
    if status == "skipped":
        _emit(run_id, release_id, f"{_STAGE_NAME}.chapter_skipped", **payload)
    return _ChinesePhaseResult(
        chapter_number=chapter_number,
        chapter_source_hash=chapter_source_hash,
        status=status,
        reason=reason,
        llm_validation_flags=llm_validation_flags if status == "failed" else None,
        llm_validation_warnings=llm_validation_warnings if status == "failed" else None,
        zh_usage_payload=usage_payload_delta(llm_client, usage_before),
    )


def _emit_generated_summary_events(
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    generated: GeneratedChapterSummary,
    model_name: str,
) -> None:
    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.generation_completed",
        chapter_number=chapter_number,
        message=f"Chinese summary generation completed for chapter {chapter_number}",
        model_name=model_name,
        status=generated.validation.status,
    )
    if generated.identity_warnings:
        warning_message = (
            f"Chapter {chapter_number} identity warning: "
            + "; ".join(generated.identity_warnings)
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.chapter_identity_warning",
            chapter_number=chapter_number,
            severity="warning",
            message=warning_message,
            warnings=generated.identity_warnings,
        )
    _emit(run_id, release_id, f"{_STAGE_NAME}.draft_generated", chapter_number=chapter_number)
    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.validation_completed",
        chapter_number=chapter_number,
        status=generated.validation.status,
    )


def _emit_llm_validation_events(
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    model_name: str,
    flags: list[str],
    warnings: list[str],
    attempt_number: int,
    action: str,
) -> None:
    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.llm_validation_completed",
        chapter_number=chapter_number,
        message=f"LLM summary validation completed for chapter {chapter_number}",
        model_name=model_name,
        flag_count=len(flags),
        warning_count=len(warnings),
        attempt_number=attempt_number,
        action=action,
    )
    if flags:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.llm_validation_warning",
            chapter_number=chapter_number,
            severity="warning",
            message=(
                f"LLM summary validation flagged chapter {chapter_number}: "
                + ", ".join(str(flag) for flag in flags)
            ),
            flags=[str(flag) for flag in flags],
            flag_count=len(flags),
            attempt_number=attempt_number,
            action=action,
        )


def _composite_chapter_hash(short_summaries: list[ValidatedSummaryZhRecord], current_hash: str) -> str:
    all_hashes = sorted(
        {row.derived_from_chapter_hash for row in short_summaries}
        | {current_hash}
    )
    return sha256("|".join(all_hashes).encode()).hexdigest() if all_hashes else current_hash


def _run_english_phase(
    *,
    job: _EnglishPhaseJob,
    db_path: Path,
    release_id: str,
    run_id: str,
    config: AppConfig,
    llm_client: LLMClient,
    prompt_en: PromptTemplate,
) -> _EnglishPhaseResult:
    conn = open_connection(db_path)
    ensure_schema(conn, "summaries")
    en_usage_before = capture_usage_snapshot(llm_client)
    try:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.english_derivation_started",
            chapter_number=job.chapter_number,
            message=f"English summary derivation started for chapter {job.chapter_number}",
            model_name=config.models.translator_name,
        )
        chapter_summary_en = derive_english_summary(
            llm_client=llm_client,
            model_name=config.models.translator_name,
            prompt_template=prompt_en.template,
            source_text_zh=job.short_record.content_zh,
            locked_glossary=job.locked_glossary,
        )
        chapter_en_record = save_derived_summary(
            conn,
            release_id=release_id,
            chapter_number=job.chapter_number,
            summary_type="chapter_summary_en_short",
            content_en=chapter_summary_en,
            source_summary_id=job.short_record.summary_id,
            source_summary_hash=hash_validated_summary(job.short_record),
            glossary_version_hash=job.glossary_version_hash,
            model_name=config.models.translator_name,
            prompt_version=prompt_en.version,
            run_id=run_id,
        )
        story_so_far_en = derive_english_summary(
            llm_client=llm_client,
            model_name=config.models.translator_name,
            prompt_template=prompt_en.template,
            source_text_zh=job.compact_story_record.content_zh,
            locked_glossary=job.locked_glossary,
        )
        story_en_record = save_derived_summary(
            conn,
            release_id=release_id,
            chapter_number=job.chapter_number,
            summary_type="story_so_far_en",
            content_en=story_so_far_en,
            source_summary_id=job.compact_story_record.summary_id,
            source_summary_hash=hash_validated_summary(job.compact_story_record),
            glossary_version_hash=job.glossary_version_hash,
            model_name=config.models.translator_name,
            prompt_version=prompt_en.version,
            run_id=run_id,
        )
    except Exception as exc:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.english_derivation_failed",
            chapter_number=job.chapter_number,
            severity="error",
            message=f"English summary derivation failed for chapter {job.chapter_number}: {exc}",
            model_name=config.models.translator_name,
            reason=str(exc),
            **usage_payload_delta(llm_client, en_usage_before),
        )
        raise
    finally:
        conn.close()

    return _EnglishPhaseResult(
        chapter_number=job.chapter_number,
        chapter_record=chapter_en_record.to_json_dict(),
        story_record=story_en_record.to_json_dict(),
        en_artifact=job.en_artifact,
        en_usage_payload=usage_payload_delta(llm_client, en_usage_before),
    )


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
    force: bool = False,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    chapter_refs = list_extracted_chapters(
        paths,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
    )
    if not chapter_refs:
        raise FileNotFoundError(
            f"No extracted chapters found for release {release_id}: {paths.extracted_chapters_dir}"
        )

    _emit(run_id, release_id, f"{_STAGE_NAME}.started", total_chapters=len(chapter_refs))
    client = _build_llm_client(config_obj, llm_client)
    prompt_structured = load_prompt("summary_zh_structured.txt")
    prompt_validate = load_prompt("summary_zh_validate.txt")
    prompt_compact = load_prompt("summary_story_compact.txt")
    prompt_en = load_prompt("summary_en_derive.txt")
    exclude_patterns = [
        re.compile(pattern)
        for pattern in config_obj.summaries.exclude_chapter_patterns
    ]

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "glossary")
    ensure_schema(conn, "summaries")
    zh_skip_until = 0
    story_skip_until = 0
    en_skip_until = 0
    if resume and not force:
        checkpoint = get_summary_checkpoint(conn, release_id=release_id, run_id=run_id)
        if checkpoint is not None:
            zh_skip_until, story_skip_until, en_skip_until = checkpoint
            logger.info(
                "Resuming summaries: zh_skip_until={}, story_skip_until={}, en_skip_until={}",
                zh_skip_until,
                story_skip_until,
                en_skip_until,
            )
    conn.close()

    results_by_chapter: dict[int, dict[str, Any]] = {}
    chinese_results: dict[int, _ChinesePhaseResult] = {}
    ordered_numbers = [ref.chapter_number for ref in chapter_refs]

    phase1_refs = [ref for ref in chapter_refs if ref.chapter_number > zh_skip_until]
    with ThreadPoolExecutor(max_workers=config_obj.summaries.chapter_concurrency) as executor:
        chinese_futures = []
        for ref in phase1_refs:
            raise_if_stop_requested(
                stop_token,
                checkpoint={"chapter_artifacts": list(results_by_chapter.values())},
                message="Summaries preprocess stopped before next chapter",
            )
            chinese_futures.append(
                executor.submit(
                    _run_chinese_phase,
                    ref=ref,
                    db_path=paths.db_path,
                    release_id=release_id,
                    run_id=run_id,
                    config=config_obj,
                    llm_client=client,
                    prompt_structured=prompt_structured,
                    prompt_validate=prompt_validate,
                    cache_root=paths.release_root / "cache" / "llm",
                    exclude_patterns=exclude_patterns,
                )
            )
        for chinese_future in as_completed(chinese_futures):
            chinese_result = chinese_future.result()
            chinese_results[chinese_result.chapter_number] = chinese_result
            entry: dict[str, Any] = {
                "chapter_number": chinese_result.chapter_number,
                "chapter_source_hash": chinese_result.chapter_source_hash,
            }
            if chinese_result.status == "skipped":
                entry["status"] = "skipped"
                if chinese_result.reason is not None:
                    entry["reason"] = chinese_result.reason
            elif chinese_result.status == "failed":
                entry["status"] = "failed"
                if chinese_result.reason is not None:
                    entry["reason"] = chinese_result.reason
            if chinese_result.warnings:
                entry["warnings"] = chinese_result.warnings
            if chinese_result.llm_validation_flags:
                entry["llm_validation_flags"] = chinese_result.llm_validation_flags
            if chinese_result.llm_validation_warnings:
                entry["llm_validation_warnings"] = chinese_result.llm_validation_warnings
            results_by_chapter[chinese_result.chapter_number] = entry

    if phase1_refs:
        conn = open_connection(paths.db_path)
        ensure_schema(conn, "summaries")
        try:
            new_zh_checkpoint = _advance_chinese_checkpoint(
                completed=chinese_results,
                current=zh_skip_until,
                ordered_numbers=ordered_numbers,
            )
            if new_zh_checkpoint > zh_skip_until:
                set_summary_checkpoint(
                    conn,
                    release_id=release_id,
                    run_id=run_id,
                    zh_last_chapter=new_zh_checkpoint,
                )
                zh_skip_until = new_zh_checkpoint
        finally:
            conn.close()

    failed_chinese = [
        result
        for result in chinese_results.values()
        if result.status == "failed"
    ]
    if failed_chinese:
        failed_chinese.sort(key=lambda result: result.chapter_number)
        failed_chapters = [result.chapter_number for result in failed_chinese]
        failure_reasons = {
            str(result.chapter_number): result.reason or "generation_failed"
            for result in failed_chinese
        }
        chapter_results = [
            results_by_chapter[number]
            for number in ordered_numbers
            if number in results_by_chapter
        ]
        message = (
            "Summary generation failed for chapter(s): "
            + ", ".join(str(chapter) for chapter in failed_chapters)
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.failed",
            severity="error",
            message=message,
            failed=len(failed_chapters),
            failed_chapters=failed_chapters,
            failure_reasons=failure_reasons,
            **capture_usage_snapshot(client).to_payload(),
        )
        return {
            "status": "failed",
            "release_id": release_id,
            "run_id": run_id,
            "chapters_processed": sum(
                1 for result in chapter_results if result.get("status") not in {"skipped", "failed"}
            ),
            "chapters_failed": len(failed_chapters),
            "failed_chapters": failed_chapters,
            "failure_reasons": failure_reasons,
            "chapter_artifacts": chapter_results,
            **capture_usage_snapshot(client).to_payload(),
        }

    english_jobs: list[_EnglishPhaseJob] = []
    conn = open_connection(paths.db_path)
    ensure_schema(conn, "glossary")
    ensure_schema(conn, "summaries")
    try:
        prior_full = list_validated_summaries(
            conn,
            release_id=release_id,
            summary_type="story_so_far_zh",
            max_chapter_number=story_skip_until,
        )
        previous_story_text = prior_full[-1].content_zh if prior_full else ""
        prior_compact = list_validated_summaries(
            conn,
            release_id=release_id,
            summary_type="story_so_far_zh_compact",
            max_chapter_number=story_skip_until,
        )
        previous_compact_text = prior_compact[-1].content_zh if prior_compact else ""

        for ref in chapter_refs:
            chapter_number = ref.chapter_number
            if chapter_number <= story_skip_until:
                continue
            raise_if_stop_requested(
                stop_token,
                checkpoint={"chapter_artifacts": list(results_by_chapter.values())},
                message="Summaries preprocess stopped before story assembly",
            )
            existing_result = chinese_results.get(chapter_number)
            is_checkpointable_skip = (
                _is_excluded(ref, exclude_patterns)
                or is_non_story_chapter(conn, release_id=release_id, chapter_number=chapter_number)
            )
            if existing_result is not None and existing_result.status == "skipped":
                is_checkpointable_skip = _checkpoint_can_advance(existing_result)
            if is_checkpointable_skip or (existing_result is not None and existing_result.status == "skipped"):
                if chapter_number not in results_by_chapter:
                    results_by_chapter[chapter_number] = {
                        "chapter_number": chapter_number,
                        "chapter_source_hash": ref.chapter_source_hash or "",
                        "status": "skipped",
                        "reason": (
                            existing_result.reason
                            if existing_result is not None
                            else "non_story_chapter"
                        ),
                    }
                if is_checkpointable_skip:
                    set_summary_checkpoint(
                        conn,
                        release_id=release_id,
                        run_id=run_id,
                        story_last_chapter=chapter_number,
                    )
                    story_skip_until = chapter_number
                continue

            short_record = (
                existing_result.short_record
                if existing_result is not None and existing_result.short_record is not None
                else get_validated_summary(
                    conn,
                    release_id=release_id,
                    chapter_number=chapter_number,
                    summary_type="chapter_summary_zh_short",
                )
            )
            structured_record = (
                existing_result.structured_record
                if existing_result is not None and existing_result.structured_record is not None
                else get_validated_summary(
                    conn,
                    release_id=release_id,
                    chapter_number=chapter_number,
                    summary_type="chapter_summary_zh_structured",
                )
            )
            if short_record is None or structured_record is None:
                if existing_result is not None and existing_result.status == "skipped":
                    continue
                raise RuntimeError(
                    "missing_chinese_summary_for_story_phase: "
                    f"release={release_id}, chapter={chapter_number}"
                )

            short_summaries = list_validated_summaries(
                conn,
                release_id=release_id,
                summary_type="chapter_summary_zh_short",
                max_chapter_number=chapter_number,
            )
            composite_hash = _composite_chapter_hash(
                short_summaries,
                ref.chapter_source_hash or short_record.derived_from_chapter_hash,
            )
            if previous_story_text.strip():
                story_text = (
                    previous_story_text.rstrip("\n")
                    + "\n"
                    + f"第{chapter_number}章：{short_record.content_zh.strip()}"
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
            compact_text, compact_source_hash = compact_story_so_far(
                llm_client=client,
                release_id=release_id,
                chapter_number=chapter_number,
                model_name=config_obj.models.analyst_name,
                prompt_template=prompt_compact.template,
                prompt_version=prompt_compact.version,
                previous_story_so_far_zh_compact=previous_compact_text,
                chapter_summary_zh_short=short_record.content_zh,
                max_tokens=config_obj.summaries.story_compact_max_tokens,
                cache_root=paths.release_root / "cache" / "llm",
            )
            compact_record = save_validated_summary(
                conn,
                release_id=release_id,
                chapter_number=chapter_number,
                summary_type="story_so_far_zh_compact",
                content_zh=compact_text,
                derived_from_chapter_hash=compact_source_hash,
                run_id=run_id,
                validation_status="approved",
            )

            zh_artifact = paths.summaries_dir / f"chapter-{chapter_number}-zh.json"
            en_artifact = paths.summaries_dir / f"chapter-{chapter_number}-en.json"
            artifact_flags, artifact_llm_warnings, artifact_warnings = _load_validated_artifact_notes(
                zh_artifact
            )
            llm_validation_flags = (
                existing_result.llm_validation_flags
                if existing_result is not None and existing_result.llm_validation_flags is not None
                else artifact_flags
            )
            llm_validation_warnings = (
                existing_result.llm_validation_warnings
                if existing_result is not None and existing_result.llm_validation_warnings is not None
                else artifact_llm_warnings
            )
            warnings = (
                existing_result.warnings
                if existing_result is not None and existing_result.warnings is not None
                else artifact_warnings
            )
            _write_json(
                zh_artifact,
                {
                    "release_id": release_id,
                    "run_id": run_id,
                    "chapter_number": chapter_number,
                    "schema_version": 1,
                    "validated": {
                        "chapter_summary_zh_structured": structured_record.to_json_dict(),
                        "chapter_summary_zh_short": short_record.to_json_dict(),
                        "story_so_far_zh": story_record.to_json_dict(),
                        "story_so_far_zh_compact": compact_record.to_json_dict(),
                    },
                    "llm_validation_flags": llm_validation_flags or [],
                    "llm_validation_warnings": llm_validation_warnings or [],
                    "warnings": warnings or [],
                },
            )
            previous_story_text = story_text
            previous_compact_text = compact_text
            zh_usage_payload = (
                existing_result.zh_usage_payload
                if existing_result is not None and existing_result.zh_usage_payload is not None
                else {field: 0 for field in LLM_USAGE_PAYLOAD_FIELDS}
            )
            result_entry = results_by_chapter.setdefault(
                chapter_number,
                {
                    "chapter_number": chapter_number,
                    "chapter_source_hash": ref.chapter_source_hash or "",
                },
            )
            result_entry.update(
                {
                    "zh_artifact": str(zh_artifact),
                    "en_artifact": str(en_artifact),
                    "warnings": warnings or [],
                }
            )
            locked_glossary = list_locked_entries(conn, release_id=release_id)
            english_jobs.append(
                _EnglishPhaseJob(
                    chapter_number=chapter_number,
                    locked_glossary=locked_glossary,
                    glossary_version_hash=hash_locked_glossary(locked_glossary),
                    short_record=short_record,
                    compact_story_record=compact_record,
                    en_artifact=en_artifact,
                    zh_usage_payload=zh_usage_payload,
                )
            )
            set_summary_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                story_last_chapter=chapter_number,
            )
            story_skip_until = chapter_number
    finally:
        conn.close()

    phase3_jobs = [job for job in english_jobs if job.chapter_number > en_skip_until]
    completed_english: dict[int, _EnglishPhaseResult] = {}
    with ThreadPoolExecutor(max_workers=config_obj.summaries.chapter_concurrency) as executor:
        english_futures = {
            executor.submit(
                _run_english_phase,
                job=job,
                db_path=paths.db_path,
                release_id=release_id,
                run_id=run_id,
                config=config_obj,
                llm_client=client,
                prompt_en=prompt_en,
            ): job
            for job in phase3_jobs
        }
        for english_future in as_completed(english_futures):
            job = english_futures[english_future]
            english_result = english_future.result()
            completed_english[english_result.chapter_number] = english_result
            _write_json(
                english_result.en_artifact,
                {
                    "release_id": release_id,
                    "run_id": run_id,
                    "chapter_number": english_result.chapter_number,
                    "schema_version": 1,
                    "derived": {
                        "chapter_summary_en_short": english_result.chapter_record,
                        "story_so_far_en": english_result.story_record,
                    },
                },
            )
            results_by_chapter[english_result.chapter_number]["en_artifact"] = str(english_result.en_artifact)
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.english_derivation_completed",
                chapter_number=english_result.chapter_number,
                message=f"English summary derivation completed for chapter {english_result.chapter_number}",
                model_name=config_obj.models.translator_name,
                summary_count=2,
                **english_result.en_usage_payload,
            )
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.chapter_completed",
                chapter_number=english_result.chapter_number,
                summary_count=5,
                **_sum_usage_payloads(job.zh_usage_payload, english_result.en_usage_payload),
            )

    if completed_english:
        max_completed_en = max(completed_english)
        conn = open_connection(paths.db_path)
        ensure_schema(conn, "summaries")
        try:
            set_summary_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                en_last_chapter=max_completed_en,
            )
        finally:
            conn.close()

    chapter_results = [
        results_by_chapter[number]
        for number in ordered_numbers
        if number in results_by_chapter
    ]
    processed_count = sum(
        1 for result in chapter_results if result.get("status") != "skipped"
    )
    skipped_count = sum(1 for result in chapter_results if result.get("status") == "skipped")
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
