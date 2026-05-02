from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loguru import logger

from resemantica.db.sqlite import open_connection
from resemantica.epub.models import PlaceholderEntry
from resemantica.epub.placeholders import restore_from_placeholders
from resemantica.llm.client import LLMClient, capture_usage_snapshot, usage_payload_delta
from resemantica.llm.prompts import load_prompt
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.translation.bundle_context import (
    format_bundle_for_pass1,
    format_glossary_for_pass3,
    load_bundles_for_chapter,
)
from resemantica.translation.checkpoints import (
    ensure_checkpoint_schema,
    load_checkpoint,
    save_checkpoint,
)
from resemantica.translation.pass1 import translate_pass1
from resemantica.translation.pass2 import translate_pass2
from resemantica.translation.pass3 import translate_pass3
from resemantica.translation.risk import classify_paragraph_risk_from_text
from resemantica.translation.validators import (
    validate_basic_fidelity,
    validate_pass3_integrity,
    validate_structure,
)
from resemantica.utils import _build_llm_client, _read_json, _write_json

_PLACEHOLDER_RE = re.compile(r"\u27e6/?[A-Z]+_\d+\u27e7")


def _placeholder_tokens(text: str) -> list[str]:
    return _PLACEHOLDER_RE.findall(text)


def _split_for_retry(text: str, max_chars: int = 1500) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pattern = re.compile(r"[^\u3002\uff01\uff1f!?\\.]+[\u3002\uff01\uff1f!?\\.]?")
    parts = [piece for piece in pattern.findall(text) if piece]
    if not parts:
        return [text[index : index + max_chars] for index in range(0, len(text), max_chars)]

    segments: list[str] = []
    current = ""
    for part in parts:
        candidate = current + part
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            segments.append(current)
            current = part
            continue
        segments.append(part[:max_chars])
        current = part[max_chars:]
    if current:
        segments.append(current)
    return segments


def _emit_translation_event(
    *,
    release_id: str,
    run_id: str,
    event_type: str,
    chapter_number: int,
    block_id: str | None = None,
    severity: str = "info",
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    try:
        from resemantica.orchestration.events import emit_event

        emit_event(
            run_id,
            release_id,
            f"translate-chapter.{event_type}",
            "translate-chapter",
            chapter_number=chapter_number,
            block_id=block_id,
            severity=severity,
            message=message,
            payload=payload,
        )
    except Exception:
        logger.opt(exception=True).debug("Failed to emit translation event {}", event_type)


def _is_blocking_restore_warning(warning: str) -> bool:
    return warning.startswith("Unknown placeholder") or warning.startswith(
        "Unexpected closing placeholder"
    ) or warning.startswith("Dangling opening placeholder")


def _to_placeholder_entries(raw_entries: list[dict[str, Any]]) -> list[PlaceholderEntry]:
    return [PlaceholderEntry(**entry) for entry in raw_entries]


def _prevalidate_source(source_text: str) -> str:
    tokens = _PLACEHOLDER_RE.findall(source_text)
    open_ids = {t.strip("\u27e6\u27e7") for t in tokens if not t.startswith("\u27e6/")}
    close_ids = {t.strip("\u27e6/\u27e7") for t in tokens if t.startswith("\u27e6/")}
    orphaned_closes = close_ids - open_ids
    if orphaned_closes:
        return _PLACEHOLDER_RE.sub("", source_text)
    return source_text


# ---------------------------------------------------------------------------
# Phase 1: Initial translation (translator model)
# ---------------------------------------------------------------------------

def translate_chapter_pass1(
    *,
    release_id: str,
    chapter_number: int,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    llm_client: LLMClient | None = None,
    force: bool = False,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    chapter_path = paths.extracted_chapters_dir / f"chapter-{chapter_number}.json"
    placeholder_path = paths.extracted_placeholders_dir / f"chapter-{chapter_number}.json"
    if not chapter_path.exists():
        raise FileNotFoundError(f"Extracted chapter artifact not found: {chapter_path}")
    if not placeholder_path.exists():
        raise FileNotFoundError(f"Placeholder map not found: {placeholder_path}")

    chapter_payload = _read_json(chapter_path)
    placeholder_payload = _read_json(placeholder_path)
    source_hash = str(chapter_payload["chapter_source_hash"])

    records = sorted(
        list(chapter_payload.get("records", [])),
        key=lambda record: (
            int(record.get("block_order", 0)),
            int(record.get("segment_order") or 0),
        ),
    )
    placeholders_by_block = {
        key: _to_placeholder_entries(value)
        for key, value in dict(placeholder_payload.get("blocks", {})).items()
    }

    bundles_by_block = load_bundles_for_chapter(
        release_id=release_id,
        chapter_number=chapter_number,
        config=config_obj,
        project_root=project_root,
    )

    run_root = paths.release_root / "runs" / run_id
    translation_dir = run_root / "translation" / f"chapter-{chapter_number}"
    pass1_artifact_path = translation_dir / "pass1.json"

    pass1_prompt = load_prompt("translate_pass1.txt")
    model_name = config_obj.models.translator_name
    client = _build_llm_client(config_obj, llm_client)
    usage_before = capture_usage_snapshot(client)

    conn = open_connection(paths.db_path)
    ensure_checkpoint_schema(conn)

    try:
        pass1_structure_checks: list[dict[str, Any]] = []
        pass1_checkpoint = load_checkpoint(
            conn,
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            pass_name="pass1",
            source_hash=source_hash,
            prompt_version=pass1_prompt.version,
        )

        if (
            not force
            and pass1_checkpoint is not None
            and pass1_checkpoint.status == "success"
            and Path(pass1_checkpoint.artifact_path).exists()
        ):
            pass1_payload = _read_json(Path(pass1_checkpoint.artifact_path))
            pass1_structure_checks = list(pass1_payload.get("structure_validation", []))
            logger.info("Chapter {} pass1: using cached artifact", chapter_number)
        else:
            pass1_blocks: list[dict[str, Any]] = []

            for record in records:
                source_text = str(record["source_text_zh"])
                cleaned_source = _prevalidate_source(source_text)
                parent_block_id = str(record["parent_block_id"])
                block_id = str(record["block_id"])
                placeholder_entries = placeholders_by_block.get(parent_block_id, [])
                bundle = bundles_by_block.get(block_id) if bundles_by_block else None
                bundle_ctx = format_bundle_for_pass1(bundle) if bundle else {
                    "glossary": "",
                    "alias_resolutions": "",
                    "matched_idioms": "",
                    "continuity_notes": "",
                }
                _emit_translation_event(
                    release_id=release_id,
                    run_id=run_id,
                    event_type="paragraph_started",
                    chapter_number=chapter_number,
                    block_id=block_id,
                    message=f"Pass1 started for {block_id}",
                    payload={"pass_name": "pass1"},
                )

                draft_text = translate_pass1(
                    client=client,
                    model_name=model_name,
                    prompt_template=pass1_prompt.template,
                    source_text=cleaned_source,
                    glossary=bundle_ctx["glossary"],
                    alias_resolutions=bundle_ctx["alias_resolutions"],
                    matched_idioms=bundle_ctx["matched_idioms"],
                    continuity_notes=bundle_ctx["continuity_notes"],
                )
                structure = validate_structure(cleaned_source, draft_text)
                pass1_structure_checks.append(
                    {
                        "stage": "pass1",
                        "block_id": block_id,
                        "status": structure.status,
                        "errors": structure.errors,
                        "warnings": structure.warnings,
                    }
                )

                if structure.is_valid:
                    restored_text, restore_warnings = restore_from_placeholders(
                        draft_text,
                        placeholder_entries,
                    )
                    blocking_restore_warnings = [
                        warning for warning in restore_warnings if _is_blocking_restore_warning(warning)
                    ]
                    if blocking_restore_warnings:
                        pass1_structure_checks.append(
                            {
                                "stage": "pass1_restore",
                                "block_id": block_id,
                                "status": "failed",
                                "errors": blocking_restore_warnings,
                                "warnings": restore_warnings,
                            }
                        )
                        structure = validate_structure(cleaned_source, "")
                    else:
                        pass1_blocks.append(
                            {
                                "block_id": block_id,
                                "parent_block_id": parent_block_id,
                                "source_text_zh": cleaned_source,
                                "draft_text": draft_text,
                                "restored_text": restored_text,
                                "was_resegmented": False,
                                "segments": [],
                            }
                        )
                        _emit_translation_event(
                            release_id=release_id,
                            run_id=run_id,
                            event_type="paragraph_completed",
                            chapter_number=chapter_number,
                            block_id=block_id,
                            message=f"Pass1 completed for {block_id}",
                            payload={"pass_name": "pass1"},
                        )
                        continue

                if _placeholder_tokens(cleaned_source):
                    pass1_blocks.append(
                        {
                            "block_id": block_id,
                            "parent_block_id": parent_block_id,
                            "source_text_zh": cleaned_source,
                            "draft_text": draft_text,
                            "restored_text": "",
                            "was_resegmented": False,
                            "segments": [],
                            "status": "failed",
                            "errors": structure.errors,
                        }
                    )
                    logger.warning("Chapter {} block {}: pass1 failed", chapter_number, block_id)
                    continue

                retry_segments = _split_for_retry(cleaned_source, max_chars=750)
                if len(retry_segments) <= 1:
                    pass1_blocks.append(
                        {
                            "block_id": block_id,
                            "parent_block_id": parent_block_id,
                            "source_text_zh": cleaned_source,
                            "draft_text": draft_text,
                            "restored_text": "",
                            "was_resegmented": False,
                            "segments": [],
                            "status": "failed",
                            "errors": structure.errors,
                        }
                    )
                    logger.warning("Chapter {} block {}: pass1 failed", chapter_number, block_id)
                    _emit_translation_event(
                        release_id=release_id,
                        run_id=run_id,
                        event_type="validation_failed",
                        chapter_number=chapter_number,
                        block_id=block_id,
                        severity="error",
                        message=f"Pass1 validation failed for {block_id}",
                        payload={"errors": structure.errors},
                    )
                    continue

                segment_payloads: list[dict[str, Any]] = []
                segment_failed = False
                _emit_translation_event(
                    release_id=release_id,
                    run_id=run_id,
                    event_type="paragraph_retry",
                    chapter_number=chapter_number,
                    block_id=block_id,
                    message=f"Retrying {block_id} as {len(retry_segments)} segments",
                    payload={"segment_count": len(retry_segments), "pass_name": "pass1"},
                )
                for segment_index, segment_source in enumerate(retry_segments, start=1):
                    segment_id = f"{parent_block_id}_seg{segment_index:02d}"
                    segment_cleaned = _prevalidate_source(segment_source)
                    segment_draft = translate_pass1(
                        client=client,
                        model_name=model_name,
                        prompt_template=pass1_prompt.template,
                        source_text=segment_cleaned,
                        glossary=bundle_ctx["glossary"],
                        alias_resolutions=bundle_ctx["alias_resolutions"],
                        matched_idioms=bundle_ctx["matched_idioms"],
                        continuity_notes=bundle_ctx["continuity_notes"],
                    )
                    segment_structure = validate_structure(segment_cleaned, segment_draft)
                    pass1_structure_checks.append(
                        {
                            "stage": "pass1_resegment",
                            "block_id": segment_id,
                            "status": segment_structure.status,
                            "errors": segment_structure.errors,
                            "warnings": segment_structure.warnings,
                        }
                    )
                    if not segment_structure.is_valid:
                        segment_failed = True
                    segment_payloads.append(
                        {
                            "segment_id": segment_id,
                            "source_text_zh": segment_cleaned,
                            "draft_text": segment_draft,
                        }
                    )

                pass1_blocks.append(
                    {
                        "block_id": parent_block_id,
                        "parent_block_id": parent_block_id,
                        "source_text_zh": cleaned_source,
                        "draft_text": "",
                        "restored_text": "",
                        "was_resegmented": True,
                        "segments": segment_payloads,
                        "status": "failed" if segment_failed else "success",
                        "errors": [] if not segment_failed else ["Resegmentation pass1 failed."],
                    }
                )
                if segment_failed:
                    logger.warning(
                        "Chapter {} block {}: resegmentation failed",
                        chapter_number,
                        parent_block_id,
                    )
                    _emit_translation_event(
                        release_id=release_id,
                        run_id=run_id,
                        event_type="validation_failed",
                        chapter_number=chapter_number,
                        block_id=parent_block_id,
                        severity="error",
                        message=f"Pass1 resegmentation failed for {parent_block_id}",
                    )

            pass1_failed = any(block.get("status") == "failed" for block in pass1_blocks)
            pass1_payload = {
                "release_id": release_id,
                "run_id": run_id,
                "chapter_number": chapter_number,
                "pass_name": "pass1",
                "model_name": model_name,
                "prompt_version": pass1_prompt.version,
                "source_hash": source_hash,
                "blocks": pass1_blocks,
                "structure_validation": pass1_structure_checks,
                "status": "failed" if pass1_failed else "success",
            }
            _write_json(pass1_artifact_path, pass1_payload)
            save_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                pass_name="pass1",
                source_hash=source_hash,
                prompt_version=pass1_prompt.version,
                status=str(pass1_payload["status"]),
                artifact_path=str(pass1_artifact_path),
            )
            if pass1_failed:
                failed_count = sum(1 for b in pass1_blocks if b.get("status") == "failed")
                logger.warning(
                    "Chapter {} pass1: {}/{} blocks failed, proceeding to pass2",
                    chapter_number,
                    failed_count,
                    len(pass1_blocks),
                )

        return {
            "status": str(pass1_payload.get("status", "unknown")),
            "pass1_artifact": str(pass1_artifact_path),
            "blocks": pass1_payload.get("blocks", []),
            **usage_payload_delta(client, usage_before),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase 2: Correction (analyst model)
# ---------------------------------------------------------------------------

def translate_chapter_pass2(
    *,
    release_id: str,
    chapter_number: int,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    llm_client: LLMClient | None = None,
    force: bool = False,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    chapter_path = paths.extracted_chapters_dir / f"chapter-{chapter_number}.json"
    placeholder_path = paths.extracted_placeholders_dir / f"chapter-{chapter_number}.json"
    if not chapter_path.exists():
        raise FileNotFoundError(f"Extracted chapter artifact not found: {chapter_path}")
    if not placeholder_path.exists():
        raise FileNotFoundError(f"Placeholder map not found: {placeholder_path}")

    placeholder_payload = _read_json(placeholder_path)
    source_hash = str(_read_json(chapter_path)["chapter_source_hash"])

    placeholders_by_block = {
        key: _to_placeholder_entries(value)
        for key, value in dict(placeholder_payload.get("blocks", {})).items()
    }

    run_root = paths.release_root / "runs" / run_id
    translation_dir = run_root / "translation" / f"chapter-{chapter_number}"
    validation_dir = run_root / "validation" / f"chapter-{chapter_number}"
    pass1_artifact_path = translation_dir / "pass1.json"
    pass2_artifact_path = translation_dir / "pass2.json"
    structure_report_path = validation_dir / "structure.json"
    fidelity_report_path = validation_dir / "fidelity.json"
    chapter_report_path = validation_dir / "chapter.json"

    pass2_prompt = load_prompt("translate_pass2.txt")
    analyst_model = config_obj.models.analyst_name
    client = _build_llm_client(config_obj, llm_client)
    usage_before = capture_usage_snapshot(client)

    conn = open_connection(paths.db_path)
    ensure_checkpoint_schema(conn)

    try:
        pass1_payload = _read_json(pass1_artifact_path)

        pass2_checkpoint = load_checkpoint(
            conn,
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            pass_name="pass2",
            source_hash=source_hash,
            prompt_version=pass2_prompt.version,
        )

        if (
            not force
            and pass2_checkpoint is not None
            and pass2_checkpoint.status == "success"
            and Path(pass2_checkpoint.artifact_path).exists()
        ):
            cached_payload = _read_json(Path(pass2_checkpoint.artifact_path))
            pass2_blocks = list(cached_payload.get("blocks", []))
            pass2_structure_checks = list(cached_payload.get("structure_validation", []))
            fidelity_checks = list(cached_payload.get("fidelity_validation", []))
            pass2_payload = cached_payload
            logger.info("Chapter {} pass2: using cached artifact", chapter_number)
        else:
            pass2_blocks = []
            pass2_structure_checks = []
            fidelity_checks = []

            for block in list(pass1_payload.get("blocks", [])):
                if block.get("status") == "failed":
                    _emit_translation_event(
                        release_id=release_id,
                        run_id=run_id,
                        event_type="paragraph_skipped",
                        chapter_number=chapter_number,
                        block_id=str(block.get("block_id", "")),
                        message="Pass2 skipped failed pass1 block",
                        payload={"pass_name": "pass2"},
                    )
                    continue

                source_text = str(block["source_text_zh"])
                parent_block_id = str(block["parent_block_id"])
                placeholder_entries = placeholders_by_block.get(parent_block_id, [])

                if bool(block.get("was_resegmented")):
                    prior_segment_translations: list[str] = []
                    segment_outputs: list[dict[str, Any]] = []
                    for segment in list(block.get("segments", [])):
                        segment_id = str(segment["segment_id"])
                        segment_source = str(segment["source_text_zh"])
                        segment_draft = str(segment["draft_text"])
                        segment_corrected = translate_pass2(
                            client=client,
                            model_name=analyst_model,
                            prompt_template=pass2_prompt.template,
                            source_text=segment_source,
                            draft_text=segment_draft,
                            full_source_block=source_text,
                            prior_segment_translations=prior_segment_translations,
                        )
                        structure = validate_structure(segment_source, segment_corrected)
                        pass2_structure_checks.append(
                            {
                                "stage": "pass2_resegment",
                                "block_id": segment_id,
                                "status": structure.status,
                                "errors": structure.errors,
                                "warnings": structure.warnings,
                            }
                        )
                        if not structure.is_valid:
                            raise RuntimeError(
                                f"Pass 2 structural validation failed for segment {segment_id}."
                            )

                        prior_segment_translations.append(segment_corrected)
                        segment_outputs.append(
                            {
                                "segment_id": segment_id,
                                "output_text_en": segment_corrected,
                            }
                        )

                    corrected_text = "".join(segment["output_text_en"] for segment in segment_outputs)
                    restored_text, restore_warnings = restore_from_placeholders(
                        corrected_text,
                        placeholder_entries,
                    )
                    blocking_restore_warnings = [
                        warning for warning in restore_warnings if _is_blocking_restore_warning(warning)
                    ]
                    if blocking_restore_warnings:
                        raise RuntimeError(
                            f"Pass 2 restoration failed for block {parent_block_id}."
                        )
                    fidelity = validate_basic_fidelity(source_text, restored_text)
                    fidelity_checks.append(
                        {
                            "block_id": parent_block_id,
                            "status": fidelity.status,
                            "errors": fidelity.errors,
                            "warnings": fidelity.warnings,
                        }
                    )
                    pass2_blocks.append(
                        {
                            "block_id": parent_block_id,
                            "parent_block_id": parent_block_id,
                            "source_text_zh": source_text,
                            "output_text_en": corrected_text,
                            "restored_text_en": restored_text,
                            "segments": segment_outputs,
                            "restoration_warnings": restore_warnings,
                        }
                    )
                    _emit_translation_event(
                        release_id=release_id,
                        run_id=run_id,
                        event_type="paragraph_completed",
                        chapter_number=chapter_number,
                        block_id=parent_block_id,
                        message=f"Pass2 completed for {parent_block_id}",
                        payload={"pass_name": "pass2"},
                    )
                    continue

                block_id = str(block["block_id"])
                draft_text = str(block["draft_text"])
                corrected_text = translate_pass2(
                    client=client,
                    model_name=analyst_model,
                    prompt_template=pass2_prompt.template,
                    source_text=source_text,
                    draft_text=draft_text,
                    full_source_block=source_text,
                    prior_segment_translations=[],
                )
                structure = validate_structure(source_text, corrected_text)
                pass2_structure_checks.append(
                    {
                        "stage": "pass2",
                        "block_id": block_id,
                        "status": structure.status,
                        "errors": structure.errors,
                        "warnings": structure.warnings,
                    }
                )
                if not structure.is_valid:
                    raise RuntimeError(f"Pass 2 structural validation failed for block {block_id}.")

                restored_text, restore_warnings = restore_from_placeholders(
                    corrected_text,
                    placeholder_entries,
                )
                blocking_restore_warnings = [
                    warning for warning in restore_warnings if _is_blocking_restore_warning(warning)
                ]
                if blocking_restore_warnings:
                    raise RuntimeError(f"Pass 2 restoration failed for block {block_id}.")

                fidelity = validate_basic_fidelity(source_text, restored_text)
                fidelity_checks.append(
                    {
                        "block_id": block_id,
                        "status": fidelity.status,
                        "errors": fidelity.errors,
                        "warnings": fidelity.warnings,
                    }
                )
                pass2_blocks.append(
                    {
                        "block_id": block_id,
                        "parent_block_id": parent_block_id,
                        "source_text_zh": source_text,
                        "draft_text": draft_text,
                        "output_text_en": corrected_text,
                        "restored_text_en": restored_text,
                        "restoration_warnings": restore_warnings,
                    }
                )
                _emit_translation_event(
                    release_id=release_id,
                    run_id=run_id,
                    event_type="paragraph_completed",
                    chapter_number=chapter_number,
                    block_id=block_id,
                    message=f"Pass2 completed for {block_id}",
                    payload={"pass_name": "pass2"},
                )

            pass2_failed = any(check["status"] == "failed" for check in pass2_structure_checks) or any(
                check["status"] == "failed" for check in fidelity_checks
            )
            pass2_payload = {
                "release_id": release_id,
                "run_id": run_id,
                "chapter_number": chapter_number,
                "pass_name": "pass2",
                "model_name": analyst_model,
                "prompt_version": pass2_prompt.version,
                "source_hash": source_hash,
                "blocks": pass2_blocks,
                "structure_validation": pass2_structure_checks,
                "fidelity_validation": fidelity_checks,
                "status": "failed" if pass2_failed else "success",
            }
            _write_json(pass2_artifact_path, pass2_payload)
            save_checkpoint(
                conn,
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                pass_name="pass2",
                source_hash=source_hash,
                prompt_version=pass2_prompt.version,
                status=str(pass2_payload["status"]),
                artifact_path=str(pass2_artifact_path),
            )

        pass1_structure_checks_from_artifact = list(pass1_payload.get("structure_validation", []))
        all_structure_checks = pass1_structure_checks_from_artifact + pass2_structure_checks
        _write_json(
            structure_report_path,
            {
                "release_id": release_id,
                "run_id": run_id,
                "chapter_number": chapter_number,
                "validation_type": "structural",
                "status": "failed"
                if any(check["status"] == "failed" for check in all_structure_checks)
                else "success",
                "checks": all_structure_checks,
            },
        )

        _write_json(
            fidelity_report_path,
            {
                "release_id": release_id,
                "run_id": run_id,
                "chapter_number": chapter_number,
                "validation_type": "fidelity",
                "status": "failed" if any(check["status"] == "failed" for check in fidelity_checks) else "success",
                "checks": fidelity_checks,
            },
        )

        chapter_status = "failed" if (
            pass1_payload.get("status") == "failed"
            or any(check["status"] == "failed" for check in pass2_structure_checks)
        ) else "success"
        pass3_enabled = config_obj.translation.pass3_default
        _write_json(
            chapter_report_path,
            {
                "release_id": release_id,
                "run_id": run_id,
                "chapter_number": chapter_number,
                "validation_type": "chapter_level",
                "status": chapter_status,
                "pass1_status": str(pass1_payload.get("status", "unknown")),
                "pass2_status": str(pass2_payload.get("status", "unknown")),
                "pass3_enabled": pass3_enabled,
            },
        )

        pass2_failed = any(check["status"] == "failed" for check in pass2_structure_checks) or any(
            check["status"] == "failed" for check in fidelity_checks
        )
        if pass2_failed:
            raise RuntimeError("Pass 2 failed validation.")

        return {
            "status": "success",
            "pass2_artifact": str(pass2_artifact_path),
            "blocks": pass2_blocks,
            **usage_payload_delta(client, usage_before),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase 3: Polish (analyst model, optional)
# ---------------------------------------------------------------------------

def translate_chapter_pass3(
    *,
    release_id: str,
    chapter_number: int,
    run_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    if not config_obj.translation.pass3_default:
        return {"status": "skipped", "pass3_artifact": None}

    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    run_root = paths.release_root / "runs" / run_id
    translation_dir = run_root / "translation" / f"chapter-{chapter_number}"
    pass2_artifact_path = translation_dir / "pass2.json"
    pass3_artifact_path = translation_dir / "pass3.json"

    if not pass2_artifact_path.exists():
        logger.warning("Chapter {} pass3: pass2 artifact not found, skipping", chapter_number)
        return {"status": "skipped", "pass3_artifact": None}

    pass2_payload = _read_json(pass2_artifact_path)
    pass2_blocks = list(pass2_payload.get("blocks", []))

    if not pass2_blocks:
        return {"status": "skipped", "pass3_artifact": None}

    pass3_prompt = load_prompt("translate_pass3.txt")
    model_name = config_obj.models.analyst_name
    client = _build_llm_client(config_obj, llm_client)
    usage_before = capture_usage_snapshot(client)
    source_hash = str(pass2_payload.get("source_hash", ""))

    conn = open_connection(paths.db_path)
    ensure_checkpoint_schema(conn)

    try:
        pass3_checkpoint = load_checkpoint(
            conn,
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            pass_name="pass3",
            source_hash=source_hash,
            prompt_version=pass3_prompt.version,
        )

        if (
            pass3_checkpoint is not None
            and pass3_checkpoint.status == "success"
            and Path(pass3_checkpoint.artifact_path).exists()
        ):
            logger.info("Chapter {} pass3: using cached artifact", chapter_number)
            return {
                "status": "success",
                "pass3_artifact": pass3_checkpoint.artifact_path,
                **usage_payload_delta(client, usage_before),
            }

        bundles_by_block = load_bundles_for_chapter(
            release_id=release_id,
            chapter_number=chapter_number,
            config=config_obj,
            project_root=project_root,
        )

        threshold_high = config_obj.translation.risk_threshold_high
        pass3_blocks: list[dict[str, Any]] = []
        risk_classifications: list[dict[str, Any]] = []
        pass3_integrity_checks: list[dict[str, Any]] = []

        for block in pass2_blocks:
            source_text = str(block["source_text_zh"])
            pass2_output = str(block["output_text_en"])
            block_id = str(block["block_id"])

            risk = classify_paragraph_risk_from_text(
                source_text=source_text,
                pass2_text=pass2_output,
                threshold_high=threshold_high,
            )
            risk_record = {"block_id": block_id, **risk.to_dict()}
            risk_classifications.append(risk_record)
            if risk.risk_class != "LOW":
                _emit_translation_event(
                    release_id=release_id,
                    run_id=run_id,
                    event_type="risk_detected",
                    chapter_number=chapter_number,
                    block_id=block_id,
                    severity="warning" if risk.risk_class == "MEDIUM" else "error",
                    message=f"{risk.risk_class} translation risk detected for {block_id}",
                    payload=risk_record,
                )

            if risk.risk_class == "HIGH":
                pass3_blocks.append(
                    {
                        "block_id": block_id,
                        "parent_block_id": block.get("parent_block_id", block_id),
                        "source_text_zh": source_text,
                        "pass2_output": pass2_output,
                        "pass3_output": None,
                        "final_output": pass2_output,
                        "risk_class": risk.risk_class,
                        "risk_score": risk.risk_score,
                        "pass_decision": "skipped_high_risk",
                    }
                )
                _emit_translation_event(
                    release_id=release_id,
                    run_id=run_id,
                    event_type="paragraph_skipped",
                    chapter_number=chapter_number,
                    block_id=block_id,
                    severity="warning",
                    message=f"Pass3 skipped high-risk block {block_id}",
                    payload={"pass_name": "pass3"},
                )
                continue

            bundle3 = bundles_by_block.get(block_id) if bundles_by_block else None
            glossary_text = format_glossary_for_pass3(bundle3) if bundle3 else ""

            polished_text = translate_pass3(
                client=client,
                model_name=model_name,
                prompt_template=pass3_prompt.template,
                source_text=source_text,
                pass2_output=pass2_output,
                glossary_text=glossary_text,
            )

            integrity = validate_pass3_integrity(
                source_text=source_text,
                pass2_output=pass2_output,
                pass3_output=polished_text,
            )
            pass3_integrity_checks.append(
                {
                    "block_id": block_id,
                    "status": integrity.status,
                    "errors": integrity.errors,
                    "warnings": integrity.warnings,
                }
            )

            if integrity.is_valid:
                final_output = polished_text
                pass_decision = "pass3_accepted"
            else:
                final_output = pass2_output
                pass_decision = "pass3_rejected_integrity_failure"

            pass3_blocks.append(
                {
                    "block_id": block_id,
                    "parent_block_id": block.get("parent_block_id", block_id),
                    "source_text_zh": source_text,
                    "pass2_output": pass2_output,
                    "pass3_output": polished_text if integrity.is_valid else None,
                    "final_output": final_output,
                    "risk_class": risk.risk_class,
                    "risk_score": risk.risk_score,
                    "pass_decision": pass_decision,
                }
            )
            _emit_translation_event(
                release_id=release_id,
                run_id=run_id,
                event_type="paragraph_completed",
                chapter_number=chapter_number,
                block_id=block_id,
                message=f"Pass3 completed for {block_id}",
                payload={"pass_name": "pass3", "pass_decision": pass_decision},
            )

        pass3_payload = {
            "release_id": release_id,
            "run_id": run_id,
            "chapter_number": chapter_number,
            "pass_name": "pass3",
            "model_name": model_name,
            "prompt_version": pass3_prompt.version,
            "source_hash": source_hash,
            "blocks": pass3_blocks,
            "risk_classifications": risk_classifications,
            "integrity_checks": pass3_integrity_checks,
            "status": "success",
        }
        _write_json(pass3_artifact_path, pass3_payload)
        save_checkpoint(
            conn,
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            pass_name="pass3",
            source_hash=source_hash,
            prompt_version=pass3_prompt.version,
            status="success",
            artifact_path=str(pass3_artifact_path),
        )

        validation_dir = run_root / "validation" / f"chapter-{chapter_number}"
        chapter_report_path = validation_dir / "chapter.json"
        if chapter_report_path.exists():
            chapter_report = _read_json(chapter_report_path)
            chapter_report["pass3_enabled"] = True
            chapter_report["risk_classifications"] = risk_classifications
            _write_json(chapter_report_path, chapter_report)

        return {
            "status": "success",
            "pass3_artifact": str(pass3_artifact_path),
            **usage_payload_delta(client, usage_before),
        }
    finally:
        conn.close()
