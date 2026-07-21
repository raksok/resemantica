from __future__ import annotations

import re
import sqlite3
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from loguru import logger

from resemantica.db.packet_repo import get_latest_packet_metadata
from resemantica.db.sqlite import open_connection
from resemantica.epub.models import PlaceholderEntry
from resemantica.epub.placeholders import restore_from_placeholders
from resemantica.llm.budget import PromptBudgetError
from resemantica.llm.client import LLMClient, capture_usage_snapshot, usage_payload_delta
from resemantica.llm.prompts import load_prompt
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.translation.bundle_context import (
    extract_glossary_target_terms_for_pass3,
    format_bundle_for_pass1,
    format_bundle_for_pass2,
    format_bundle_for_pass3,
    load_bundles_for_chapter,
)
from resemantica.translation.checkpoints import (
    ensure_checkpoint_schema,
    load_checkpoint,
    save_checkpoint,
)
from resemantica.translation.pass1 import _translate_pass1_with_diagnostics
from resemantica.translation.pass2 import (
    Pass2BatchResponseError,
    ensure_pass2_batch_prompt_within_budget,
    parse_pass2_batch_response,
    render_pass2_batch_prompt,
    translate_pass2,
)
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


def _is_symbol_only_source(text: str) -> bool:
    without_placeholders = _PLACEHOLDER_RE.sub("", text).strip()
    return not without_placeholders or not any(char.isalnum() for char in without_placeholders)


def _is_reusable_pass1_block(block: dict[str, Any], *, source_text: str) -> bool:
    if block.get("status") == "failed" or str(block.get("source_text_zh", "")) != source_text:
        return False
    if block.get("was_resegmented"):
        segments = block.get("segments")
        return isinstance(segments, list) and bool(segments) and all(
            isinstance(segment, dict) and bool(str(segment.get("draft_text", "")).strip())
            for segment in segments
        )
    return bool(str(block.get("draft_text", "")).strip())


def _reusable_pass2_blocks(
    expected_blocks: list[dict[str, Any]],
    cached_blocks: object,
) -> dict[str, dict[str, Any]]:
    expected_by_id = {str(block["block_id"]): block for block in expected_blocks}
    if len(expected_by_id) != len(expected_blocks):
        raise RuntimeError("Pass 1 contains duplicate block mappings.")
    if not isinstance(cached_blocks, list):
        raise RuntimeError("Pass 2 cache contains malformed block mappings.")

    reusable: dict[str, dict[str, Any]] = {}
    extra: list[str] = []
    malformed: list[str] = []
    seen: set[str] = set()
    for index, block in enumerate(cached_blocks):
        if not isinstance(block, dict):
            malformed.append(f"index {index}")
            continue
        block_id = str(block.get("block_id", ""))
        if not block_id or block_id in seen:
            malformed.append(block_id or f"index {index}")
            continue
        seen.add(block_id)
        expected = expected_by_id.get(block_id)
        if expected is None:
            extra.append(block_id)
            continue
        if (
            str(block.get("parent_block_id", "")) != str(expected.get("parent_block_id", ""))
            or str(block.get("source_text_zh", "")) != str(expected.get("source_text_zh", ""))
        ):
            malformed.append(block_id)
            continue
        output = block.get("restored_text_en") or block.get("output_text_en")
        if isinstance(output, str) and output.strip():
            reusable[block_id] = block

    if extra:
        raise RuntimeError(f"Pass 2 cache contains extra block mappings: {sorted(extra)}")
    if malformed:
        raise RuntimeError(f"Pass 2 cache contains malformed block mappings: {sorted(malformed)}")
    return reusable


def _split_for_retry(text: str, max_chars: int = 1500, *, force: bool = False) -> list[str]:
    if len(text) <= max_chars and not force:
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

    if len(segments) == 1 and force:
        midpoint = len(text) / 2
        boundaries = [
            match.end()
            for match in re.finditer(r"[\u3002\uff01\uff1f!?\.\uff0c,\uff1b;\uff1a:]", text)
            if not _is_symbol_only_source(text[: match.end()])
            and not _is_symbol_only_source(text[match.end() :])
        ]
        if boundaries:
            split_at = min(boundaries, key=lambda position: (abs(position - midpoint), position))
            segments = [text[:split_at], text[split_at:]]
    if "".join(segments) != text:
        return [text]
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


def _emit_pass2_fallback_event(
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    payload: dict[str, Any],
) -> None:
    block_id = payload.get("block_id")
    reason = str(payload.get("reason", "fallback"))
    _emit_translation_event(
        release_id=release_id,
        run_id=run_id,
        event_type="pass2.fallback",
        chapter_number=chapter_number,
        block_id=str(block_id) if block_id else None,
        severity="warning",
        message=f"Pass2 fallback for {block_id or 'chapter'}: {reason}",
        payload=payload,
    )


def _emit_bundle_context_missing_event(
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    pass_name: str,
    payload: dict[str, object],
) -> None:
    reason = str(payload.get("reason", "bundle_context_missing"))
    _emit_translation_event(
        release_id=release_id,
        run_id=run_id,
        event_type="bundle_context_missing",
        chapter_number=chapter_number,
        severity="warning",
        message=f"Bundle context missing for chapter {chapter_number}: {reason}",
        payload={"pass_name": pass_name, **payload},
    )


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


def _latest_packet_version_hash(
    conn: Any,
    *,
    release_id: str,
    chapter_number: int,
) -> str:
    try:
        packet_meta = get_latest_packet_metadata(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
        )
    except sqlite3.OperationalError:
        logger.warning("packet_metadata table not found, continuing without packet hash")
        return ""
    return packet_meta.packet_hash if packet_meta else ""


def _count_title_honorific_glossary_entries(bundle: Any) -> int:
    return sum(
        1
        for entry in list(getattr(bundle, "matched_glossary_entries", []))
        if str(entry.get("category", "")).strip() == "title_honorific"
    )


def _is_truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _relationship_is_reveal_gated(entry: dict[str, Any]) -> bool:
    if _is_truthy_flag(entry.get("is_masked_identity", False)):
        return True
    if _is_truthy_flag(entry.get("is_reveal_gated", False)) or _is_truthy_flag(
        entry.get("reveal_gated", False)
    ):
        return True
    if _is_truthy_flag(entry.get("requires_reveal", False)):
        return True

    if "revealed_chapter" not in entry:
        return False
    try:
        revealed_chapter = int(entry.get("revealed_chapter", 0))
        chapter_markers = [
            int(entry[key])
            for key in ("source_chapter", "start_chapter")
            if key in entry and entry[key] is not None
        ]
    except (TypeError, ValueError):
        return False
    return bool(chapter_markers) and revealed_chapter > max(chapter_markers)


def _has_reveal_gated_relationship(bundle: Any) -> bool:
    return any(
        _relationship_is_reveal_gated(dict(entry))
        for entry in list(getattr(bundle, "local_relationships", []))
    )


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
        warning_callback=lambda payload: _emit_bundle_context_missing_event(
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            pass_name="pass1",
            payload=payload,
        ),
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

    packet_version_hash = _latest_packet_version_hash(
        conn,
        release_id=release_id,
        chapter_number=chapter_number,
    )

    try:
        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="pass1.started",
            chapter_number=chapter_number,
            message=f"Pass1 started for chapter {chapter_number}",
            payload={"pass_name": "pass1", "model_name": model_name},
        )
        pass1_structure_checks: list[dict[str, Any]] = []
        used_pass1_cache = False
        pass1_checkpoint = load_checkpoint(
            conn,
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            pass_name="pass1",
            source_hash=source_hash,
            prompt_version=pass1_prompt.version,
            packet_version_hash=packet_version_hash,
        )

        existing_pass1_payload: dict[str, Any] | None = None
        reusable_blocks: dict[str, dict[str, Any]] = {}
        expected_sources = {
            str(record["block_id"]): _prevalidate_source(str(record["source_text_zh"]))
            for record in records
        }
        if (
            not force
            and pass1_checkpoint is not None
            and Path(pass1_checkpoint.artifact_path).exists()
        ):
            existing_pass1_payload = _read_json(Path(pass1_checkpoint.artifact_path))
            existing_blocks = existing_pass1_payload.get("blocks", [])
            if isinstance(existing_blocks, list):
                for block in existing_blocks:
                    if not isinstance(block, dict):
                        continue
                    block_id = str(block.get("block_id", ""))
                    source_text = expected_sources.get(block_id)
                    if source_text is not None and _is_reusable_pass1_block(
                        block,
                        source_text=source_text,
                    ):
                        reusable_blocks[block_id] = block

        if (
            not force
            and pass1_checkpoint is not None
            and pass1_checkpoint.status == "success"
            and existing_pass1_payload is not None
            and len(reusable_blocks) == len(records)
            and set(reusable_blocks) == set(expected_sources)
        ):
            used_pass1_cache = True
            pass1_payload = existing_pass1_payload
            pass1_structure_checks = list(pass1_payload.get("structure_validation", []))
            logger.info("Chapter {} pass1: using cached artifact", chapter_number)
            _emit_translation_event(
                release_id=release_id,
                run_id=run_id,
                event_type="pass1.cached",
                chapter_number=chapter_number,
                message=f"Pass1 cache hit for chapter {chapter_number}",
                payload={
                    "pass_name": "pass1",
                    "artifact_path": pass1_checkpoint.artifact_path,
                    "status": pass1_checkpoint.status,
                },
            )
        else:
            pass1_blocks: list[dict[str, Any]] = []
            pass1_structure_checks = []

            for record in records:
                source_text = str(record["source_text_zh"])
                cleaned_source = _prevalidate_source(source_text)
                parent_block_id = str(record["parent_block_id"])
                block_id = str(record["block_id"])
                placeholder_entries = placeholders_by_block.get(parent_block_id, [])
                bundle = bundles_by_block.get(block_id) if bundles_by_block else None
                bundle_ctx = format_bundle_for_pass1(bundle)
                _emit_translation_event(
                    release_id=release_id,
                    run_id=run_id,
                    event_type="paragraph_started",
                    chapter_number=chapter_number,
                    block_id=block_id,
                    message=f"Pass1 started for {block_id}",
                    payload={"pass_name": "pass1"},
                )

                reusable_block = reusable_blocks.get(block_id)
                if reusable_block is not None:
                    pass1_blocks.append(reusable_block)
                    _emit_translation_event(
                        release_id=release_id,
                        run_id=run_id,
                        event_type="paragraph_completed",
                        chapter_number=chapter_number,
                        block_id=block_id,
                        message=f"Pass1 reused successful block {block_id}",
                        payload={"pass_name": "pass1", "status": "cached"},
                    )
                    continue

                if _is_symbol_only_source(cleaned_source):
                    pass1_blocks.append(
                        {
                            "block_id": block_id,
                            "parent_block_id": parent_block_id,
                            "source_text_zh": cleaned_source,
                            "draft_text": cleaned_source,
                            "restored_text": cleaned_source,
                            "was_resegmented": False,
                            "segments": [],
                            "status": "success",
                            "passthrough": True,
                        }
                    )
                    pass1_structure_checks.append(
                        {
                            "stage": "pass1",
                            "block_id": block_id,
                            "status": "passed",
                            "errors": [],
                            "warnings": [],
                        }
                    )
                    _emit_translation_event(
                        release_id=release_id,
                        run_id=run_id,
                        event_type="paragraph_completed",
                        chapter_number=chapter_number,
                        block_id=block_id,
                        message=f"Pass1 preserved non-translatable block {block_id}",
                        payload={"pass_name": "pass1", "status": "passthrough"},
                    )
                    continue

                pass1_result = _translate_pass1_with_diagnostics(
                    client=client,
                    model_name=model_name,
                    prompt_template=pass1_prompt.template,
                    source_text=cleaned_source,
                    glossary=bundle_ctx["glossary"],
                    alias_resolutions=bundle_ctx["alias_resolutions"],
                    matched_idioms=bundle_ctx["matched_idioms"],
                    continuity_notes=bundle_ctx["continuity_notes"],
                    config=config_obj,
                    chapter_number=chapter_number,
                )
                draft_text = pass1_result.text
                structure = validate_structure(cleaned_source, draft_text)
                structure_errors = (
                    [pass1_result.failure_reason]
                    if pass1_result.failure_reason is not None
                    else structure.errors
                )
                pass1_structure_checks.append(
                    {
                        "stage": "pass1",
                        "block_id": block_id,
                        "status": structure.status,
                        "errors": structure_errors,
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
                        _emit_translation_event(
                            release_id=release_id,
                            run_id=run_id,
                            event_type="pass1.restore_failed",
                            chapter_number=chapter_number,
                            block_id=block_id,
                            severity="error",
                            message=f"Pass1 placeholder restoration failed for {block_id}",
                            payload={
                                "pass_name": "pass1",
                                "errors": blocking_restore_warnings,
                                "warnings": restore_warnings,
                            },
                        )
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
                        structure_errors = structure.errors
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
                                "status": "success",
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
                else:
                    _emit_translation_event(
                        release_id=release_id,
                        run_id=run_id,
                        event_type="pass1.structure_failed",
                        chapter_number=chapter_number,
                        block_id=block_id,
                        severity="warning",
                        message=f"Pass1 structure validation failed for {block_id}",
                        payload={
                            "pass_name": "pass1",
                            "errors": structure_errors,
                            "warnings": structure.warnings,
                        },
                    )

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
                            "errors": structure_errors,
                        }
                    )
                    _emit_translation_event(
                        release_id=release_id,
                        run_id=run_id,
                        event_type="validation_failed",
                        chapter_number=chapter_number,
                        block_id=block_id,
                        severity="error",
                        message=f"Pass1 validation failed for {block_id}",
                        payload={"pass_name": "pass1", "errors": structure_errors},
                    )
                    continue

                retry_segments = _split_for_retry(cleaned_source, max_chars=750, force=True)
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
                            "errors": structure_errors,
                        }
                    )
                    _emit_translation_event(
                        release_id=release_id,
                        run_id=run_id,
                        event_type="validation_failed",
                        chapter_number=chapter_number,
                        block_id=block_id,
                        severity="error",
                        message=f"Pass1 validation failed for {block_id}",
                        payload={"errors": structure_errors},
                    )
                    continue

                segment_payloads: list[dict[str, Any]] = []
                segment_failed = False
                segment_failure_errors: list[str] = []
                _emit_translation_event(
                    release_id=release_id,
                    run_id=run_id,
                    event_type="pass1.resegmentation_started",
                    chapter_number=chapter_number,
                    block_id=block_id,
                    severity="warning",
                    message=f"Pass1 resegmentation started for {block_id}",
                    payload={"segment_count": len(retry_segments), "pass_name": "pass1"},
                )
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
                    segment_result = _translate_pass1_with_diagnostics(
                        client=client,
                        model_name=model_name,
                        prompt_template=pass1_prompt.template,
                        source_text=segment_cleaned,
                        glossary=bundle_ctx["glossary"],
                        alias_resolutions=bundle_ctx["alias_resolutions"],
                        matched_idioms=bundle_ctx["matched_idioms"],
                        continuity_notes=bundle_ctx["continuity_notes"],
                        config=config_obj,
                        chapter_number=chapter_number,
                    )
                    segment_draft = segment_result.text
                    segment_structure = validate_structure(segment_cleaned, segment_draft)
                    segment_errors = (
                        [segment_result.failure_reason]
                        if segment_result.failure_reason is not None
                        else segment_structure.errors
                    )
                    pass1_structure_checks.append(
                        {
                            "stage": "pass1_resegment",
                            "block_id": segment_id,
                            "status": segment_structure.status,
                            "errors": segment_errors,
                            "warnings": segment_structure.warnings,
                        }
                    )
                    if not segment_structure.is_valid:
                        segment_failed = True
                        segment_failure_errors.extend(
                            f"{segment_id}: {error}" for error in segment_errors
                        )
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
                        "errors": segment_failure_errors,
                    }
                )
                if segment_failed:
                    _emit_translation_event(
                        release_id=release_id,
                        run_id=run_id,
                        event_type="validation_failed",
                        chapter_number=chapter_number,
                        block_id=parent_block_id,
                        severity="error",
                        message=f"Pass1 resegmentation failed for {parent_block_id}",
                        payload={"pass_name": "pass1", "errors": segment_failure_errors},
                    )
                    _emit_translation_event(
                        release_id=release_id,
                        run_id=run_id,
                        event_type="pass1.resegmentation_failed",
                        chapter_number=chapter_number,
                        block_id=parent_block_id,
                        severity="error",
                        message=f"Pass1 resegmentation failed for {parent_block_id}",
                        payload={"pass_name": "pass1", "errors": segment_failure_errors},
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
                packet_version_hash=packet_version_hash,
                status=str(pass1_payload["status"]),
                artifact_path=str(pass1_artifact_path),
            )
            if pass1_failed:
                failed_count = sum(1 for b in pass1_blocks if b.get("status") == "failed")
                _emit_translation_event(
                    release_id=release_id,
                    run_id=run_id,
                    event_type="pass1.completed",
                    chapter_number=chapter_number,
                    severity="warning",
                    message=f"Pass1 completed for chapter {chapter_number} with {failed_count} failed blocks",
                    payload={
                        "pass_name": "pass1",
                        "status": "failed",
                        "failed_count": failed_count,
                        "artifact_path": str(pass1_artifact_path),
                    },
                )
            else:
                _emit_translation_event(
                    release_id=release_id,
                    run_id=run_id,
                    event_type="pass1.completed",
                    chapter_number=chapter_number,
                    message=f"Pass1 completed for chapter {chapter_number}",
                    payload={
                        "pass_name": "pass1",
                        "status": "success",
                        "artifact_path": str(pass1_artifact_path),
                    },
                )

        if used_pass1_cache:
            _emit_translation_event(
                release_id=release_id,
                run_id=run_id,
                event_type="pass1.completed",
                chapter_number=chapter_number,
                message=f"Pass1 completed for chapter {chapter_number} from cache",
                payload={
                    "pass_name": "pass1",
                    "status": "cached",
                    "artifact_path": (
                        pass1_checkpoint.artifact_path
                        if pass1_checkpoint is not None
                        else str(pass1_artifact_path)
                    ),
                },
            )
        return {
            "status": str(pass1_payload.get("status", "unknown")),
            "pass1_artifact": str(pass1_artifact_path),
            "blocks": pass1_payload.get("blocks", []),
            **usage_payload_delta(client, usage_before),
        }
    except Exception as exc:
        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="pass1.failed",
            chapter_number=chapter_number,
            severity="error",
            message=f"Pass1 failed for chapter {chapter_number}: {exc}",
            payload={"pass_name": "pass1", "reason": str(exc)},
        )
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase 2: Correction (analyst model)
# ---------------------------------------------------------------------------


class Pass2ValidationRetryableError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        block_id: str,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.block_id = block_id
        self.reason = reason
        self.payload = payload or {}


def _finalize_pass2_normal_block(
    block: dict[str, Any],
    *,
    corrected_text: str,
    placeholders_by_block: dict[str, list[PlaceholderEntry]],
    release_id: str,
    run_id: str,
    chapter_number: int,
    emit_failure_events: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    source_text = str(block["source_text_zh"])
    parent_block_id = str(block["parent_block_id"])
    block_id = str(block["block_id"])
    draft_text = str(block["draft_text"])
    placeholder_entries = placeholders_by_block.get(parent_block_id, [])

    structure = validate_structure(source_text, corrected_text)
    structure_check = {
        "stage": "pass2",
        "block_id": block_id,
        "status": structure.status,
        "errors": structure.errors,
        "warnings": structure.warnings,
    }
    if not structure.is_valid:
        payload = {"pass_name": "pass2", "errors": structure.errors}
        message = f"Pass2 structural validation failed for block {block_id}"
        if emit_failure_events:
            _emit_translation_event(
                release_id=release_id,
                run_id=run_id,
                event_type="pass2.failed",
                chapter_number=chapter_number,
                block_id=block_id,
                severity="error",
                message=message,
                payload=payload,
            )
        raise Pass2ValidationRetryableError(
            f"Pass 2 structural validation failed for block {block_id}.",
            block_id=block_id,
            reason="structural_validation_failed",
            payload=payload,
        )

    restored_text, restore_warnings = restore_from_placeholders(
        corrected_text,
        placeholder_entries,
    )
    blocking_restore_warnings = [
        warning for warning in restore_warnings if _is_blocking_restore_warning(warning)
    ]
    if blocking_restore_warnings:
        payload = {
            "pass_name": "pass2",
            "errors": blocking_restore_warnings,
            "warnings": restore_warnings,
        }
        message = f"Pass2 restoration failed for block {block_id}"
        if emit_failure_events:
            _emit_translation_event(
                release_id=release_id,
                run_id=run_id,
                event_type="pass2.failed",
                chapter_number=chapter_number,
                block_id=block_id,
                severity="error",
                message=message,
                payload=payload,
            )
        raise Pass2ValidationRetryableError(
            f"Pass 2 restoration failed for block {block_id}.",
            block_id=block_id,
            reason="restoration_failed",
            payload=payload,
        )

    fidelity = validate_basic_fidelity(source_text, restored_text)
    fidelity_check = {
        "block_id": block_id,
        "status": fidelity.status,
        "errors": fidelity.errors,
        "warnings": fidelity.warnings,
    }
    if not fidelity.is_valid and not emit_failure_events:
        raise Pass2ValidationRetryableError(
            f"Pass 2 fidelity validation failed for block {block_id}.",
            block_id=block_id,
            reason="fidelity_validation_failed",
            payload={
                "pass_name": "pass2",
                "errors": fidelity.errors,
                "warnings": fidelity.warnings,
            },
        )

    block_result = {
        "block_id": block_id,
        "parent_block_id": parent_block_id,
        "source_text_zh": source_text,
        "draft_text": draft_text,
        "output_text_en": corrected_text,
        "restored_text_en": restored_text,
        "restoration_warnings": restore_warnings,
    }
    _emit_translation_event(
        release_id=release_id,
        run_id=run_id,
        event_type="paragraph_completed",
        chapter_number=chapter_number,
        block_id=block_id,
        message=f"Pass2 completed for {block_id}",
        payload={"pass_name": "pass2"},
    )
    return block_result, [structure_check], fidelity_check


def _process_pass2_block_once(
    block: dict[str, Any],
    *,
    pass2_prompt_template: str,
    analyst_model: str,
    client: LLMClient,
    placeholders_by_block: dict[str, list[PlaceholderEntry]],
    bundles_by_block: dict[str, Any] | None,
    release_id: str,
    run_id: str,
    chapter_number: int,
    config: AppConfig,
    emit_failure_events: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    source_text = str(block["source_text_zh"])
    parent_block_id = str(block["parent_block_id"])
    placeholder_entries = placeholders_by_block.get(parent_block_id, [])

    bundle = bundles_by_block.get(parent_block_id) if bundles_by_block else None
    pass2_context = format_bundle_for_pass2(bundle)

    _emit_translation_event(
        release_id=release_id,
        run_id=run_id,
        event_type="paragraph_started",
        chapter_number=chapter_number,
        block_id=parent_block_id,
        message=f"Pass2 started for {parent_block_id}",
        payload={"pass_name": "pass2"},
    )

    if bool(block.get("passthrough")):
        passthrough_text = str(block["source_text_zh"])
        result = {
            "block_id": str(block["block_id"]),
            "parent_block_id": parent_block_id,
            "source_text_zh": passthrough_text,
            "draft_text": passthrough_text,
            "output_text_en": passthrough_text,
            "restored_text_en": passthrough_text,
            "restoration_warnings": [],
            "passthrough": True,
        }
        structure_check = {
            "stage": "pass2",
            "block_id": str(block["block_id"]),
            "status": "passed",
            "errors": [],
            "warnings": [],
        }
        fidelity_check = {
            "block_id": str(block["block_id"]),
            "status": "passed",
            "errors": [],
            "warnings": [],
        }
        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="paragraph_completed",
            chapter_number=chapter_number,
            block_id=str(block["block_id"]),
            message=f"Pass2 preserved non-translatable block {block['block_id']}",
            payload={"pass_name": "pass2", "status": "passthrough"},
        )
        return result, [structure_check], fidelity_check

    if bool(block.get("was_resegmented")):
        prior_segment_translations: list[str] = []
        segment_outputs: list[dict[str, Any]] = []
        structure_checks: list[dict[str, Any]] = []
        for segment in list(block.get("segments", [])):
            segment_id = str(segment["segment_id"])
            segment_source = str(segment["source_text_zh"])
            segment_draft = str(segment["draft_text"])
            segment_corrected = translate_pass2(
                client=client,
                model_name=analyst_model,
                prompt_template=pass2_prompt_template,
                source_text=segment_source,
                draft_text=segment_draft,
                full_source_block=source_text,
                prior_segment_translations=prior_segment_translations,
                glossary=pass2_context["glossary"],
                alias_resolutions=pass2_context["alias_resolutions"],
                matched_idioms=pass2_context["matched_idioms"],
                local_relationships=pass2_context["local_relationships"],
                continuity_notes=pass2_context["continuity_notes"],
                retrieval_evidence=pass2_context["retrieval_evidence"],
                chapter_number=chapter_number,
                block_id=parent_block_id,
                segment_id=segment_id,
                config=config,
                fallback_callback=lambda payload: _emit_pass2_fallback_event(
                    release_id=release_id,
                    run_id=run_id,
                    chapter_number=chapter_number,
                    payload=payload,
                ),
            )
            structure = validate_structure(segment_source, segment_corrected)
            structure_checks.append(
                {
                    "stage": "pass2_resegment",
                    "block_id": segment_id,
                    "status": structure.status,
                    "errors": structure.errors,
                    "warnings": structure.warnings,
                }
            )
            if not structure.is_valid:
                payload = {"pass_name": "pass2", "errors": structure.errors}
                message = f"Pass2 structural validation failed for segment {segment_id}"
                if emit_failure_events:
                    _emit_translation_event(
                        release_id=release_id,
                        run_id=run_id,
                        event_type="pass2.failed",
                        chapter_number=chapter_number,
                        block_id=segment_id,
                        severity="error",
                        message=message,
                        payload=payload,
                    )
                raise Pass2ValidationRetryableError(
                    f"Pass 2 structural validation failed for segment {segment_id}.",
                    block_id=segment_id,
                    reason="structural_validation_failed",
                    payload=payload,
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
            payload = {
                "pass_name": "pass2",
                "errors": blocking_restore_warnings,
                "warnings": restore_warnings,
            }
            message = f"Pass2 restoration failed for block {parent_block_id}"
            if emit_failure_events:
                _emit_translation_event(
                    release_id=release_id,
                    run_id=run_id,
                    event_type="pass2.failed",
                    chapter_number=chapter_number,
                    block_id=parent_block_id,
                    severity="error",
                    message=message,
                    payload=payload,
            )
            raise Pass2ValidationRetryableError(
                f"Pass 2 restoration failed for block {parent_block_id}.",
                block_id=parent_block_id,
                reason="restoration_failed",
                payload=payload,
            )
        fidelity = validate_basic_fidelity(source_text, restored_text)
        fidelity_check = {
            "block_id": parent_block_id,
            "status": fidelity.status,
            "errors": fidelity.errors,
            "warnings": fidelity.warnings,
        }
        if not fidelity.is_valid and not emit_failure_events:
            raise Pass2ValidationRetryableError(
                f"Pass 2 fidelity validation failed for block {parent_block_id}.",
                block_id=parent_block_id,
                reason="fidelity_validation_failed",
                payload={
                    "pass_name": "pass2",
                    "errors": fidelity.errors,
                    "warnings": fidelity.warnings,
                },
            )
        block_result = {
            "block_id": parent_block_id,
            "parent_block_id": parent_block_id,
            "source_text_zh": source_text,
            "output_text_en": corrected_text,
            "restored_text_en": restored_text,
            "segments": segment_outputs,
            "restoration_warnings": restore_warnings,
        }
        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="paragraph_completed",
            chapter_number=chapter_number,
            block_id=parent_block_id,
            message=f"Pass2 completed for {parent_block_id}",
            payload={"pass_name": "pass2"},
        )
        return block_result, structure_checks, fidelity_check

    block_id = str(block["block_id"])
    draft_text = str(block["draft_text"])
    corrected_text = translate_pass2(
        client=client,
        model_name=analyst_model,
        prompt_template=pass2_prompt_template,
        source_text=source_text,
        draft_text=draft_text,
        full_source_block=source_text,
        prior_segment_translations=[],
        glossary=pass2_context["glossary"],
        alias_resolutions=pass2_context["alias_resolutions"],
        matched_idioms=pass2_context["matched_idioms"],
        local_relationships=pass2_context["local_relationships"],
        continuity_notes=pass2_context["continuity_notes"],
        retrieval_evidence=pass2_context["retrieval_evidence"],
        chapter_number=chapter_number,
        block_id=block_id,
        config=config,
        fallback_callback=lambda payload: _emit_pass2_fallback_event(
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            payload=payload,
        ),
    )
    return _finalize_pass2_normal_block(
        block,
        corrected_text=corrected_text,
        placeholders_by_block=placeholders_by_block,
        release_id=release_id,
        run_id=run_id,
        chapter_number=chapter_number,
        emit_failure_events=emit_failure_events,
    )


def _process_pass2_block(
    block: dict[str, Any],
    *,
    pass2_prompt_template: str,
    analyst_model: str,
    client: LLMClient,
    placeholders_by_block: dict[str, list[PlaceholderEntry]],
    bundles_by_block: dict[str, Any] | None,
    release_id: str,
    run_id: str,
    chapter_number: int,
    config: AppConfig,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    max_attempts = config.translation.pass2_validation_retries + 1
    last_error: Pass2ValidationRetryableError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return _process_pass2_block_once(
                block,
                pass2_prompt_template=pass2_prompt_template,
                analyst_model=analyst_model,
                client=client,
                placeholders_by_block=placeholders_by_block,
                bundles_by_block=bundles_by_block,
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                config=config,
                emit_failure_events=attempt == max_attempts,
            )
        except Pass2ValidationRetryableError as exc:
            last_error = exc
            if attempt >= max_attempts:
                raise
            _emit_translation_event(
                release_id=release_id,
                run_id=run_id,
                event_type="pass2.retry",
                chapter_number=chapter_number,
                block_id=exc.block_id,
                severity="warning",
                message=(
                    f"Pass2 validation retry {attempt}/{max_attempts - 1} "
                    f"for {exc.block_id}: {exc.reason}"
                ),
                payload={
                    "pass_name": "pass2",
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "remaining_retries": max_attempts - attempt,
                    "reason": exc.reason,
                    **exc.payload,
                },
            )
    if last_error is not None:
        raise last_error
    raise RuntimeError("Pass 2 block retry failed without an attempt result.")


def _pass2_batch_item(
    block: dict[str, Any],
    *,
    bundles_by_block: dict[str, Any] | None,
) -> dict[str, Any]:
    parent_block_id = str(block["parent_block_id"])
    bundle = bundles_by_block.get(parent_block_id) if bundles_by_block else None
    pass2_context = format_bundle_for_pass2(bundle)
    source_text = str(block["source_text_zh"])
    return {
        "block_id": str(block["block_id"]),
        "source_text": source_text,
        "draft_text": str(block["draft_text"]),
        "full_source_block": source_text,
        "prior_segments": [],
        "glossary": pass2_context["glossary"],
        "alias_resolutions": pass2_context["alias_resolutions"],
        "matched_idioms": pass2_context["matched_idioms"],
        "local_relationships": pass2_context["local_relationships"],
        "continuity_notes": pass2_context["continuity_notes"],
        "retrieval_evidence": pass2_context["retrieval_evidence"],
    }


def _pass2_batch_prompt_tokens(
    batch_items: list[dict[str, Any]],
    *,
    pass2_batch_prompt_template: str,
    analyst_model: str,
    config: AppConfig,
    chapter_number: int,
) -> int:
    prompt = render_pass2_batch_prompt(
        prompt_template=pass2_batch_prompt_template,
        batch_items=batch_items,
    )
    return ensure_pass2_batch_prompt_within_budget(
        prompt,
        model_name=analyst_model,
        config=config,
        chapter_number=chapter_number,
    )


def _pack_pass2_work_units(
    blocks_to_process: list[dict[str, Any]],
    *,
    pass2_batch_prompt_template: str,
    analyst_model: str,
    bundles_by_block: dict[str, Any] | None,
    config: AppConfig,
    chapter_number: int,
) -> list[dict[str, Any]]:
    max_blocks = config.translation.pass2_batch_max_blocks
    if max_blocks == 1:
        return [{"kind": "single", "blocks": [block]} for block in blocks_to_process]

    work_units: list[dict[str, Any]] = []
    current_blocks: list[dict[str, Any]] = []
    current_items: list[dict[str, Any]] = []

    def flush_current() -> None:
        nonlocal current_blocks, current_items
        if not current_blocks:
            return
        work_units.append(
            {
                "kind": "batch",
                "blocks": current_blocks,
                "batch_items": current_items,
            }
        )
        current_blocks = []
        current_items = []

    for block in blocks_to_process:
        if bool(block.get("was_resegmented")) or bool(block.get("passthrough")):
            flush_current()
            work_units.append({"kind": "single", "blocks": [block]})
            continue

        item = _pass2_batch_item(block, bundles_by_block=bundles_by_block)
        candidate_items = [*current_items, item]
        should_split = len(candidate_items) > max_blocks
        if not should_split:
            try:
                _pass2_batch_prompt_tokens(
                    candidate_items,
                    pass2_batch_prompt_template=pass2_batch_prompt_template,
                    analyst_model=analyst_model,
                    config=config,
                    chapter_number=chapter_number,
                )
            except PromptBudgetError:
                should_split = True

        if should_split:
            flush_current()
            try:
                _pass2_batch_prompt_tokens(
                    [item],
                    pass2_batch_prompt_template=pass2_batch_prompt_template,
                    analyst_model=analyst_model,
                    config=config,
                    chapter_number=chapter_number,
                )
            except PromptBudgetError:
                work_units.append({"kind": "single", "blocks": [block]})
                continue

        current_blocks.append(block)
        current_items.append(item)

    flush_current()
    return work_units


def _emit_pass2_batch_fallback_event(
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
    batch_index: int,
    blocks: list[dict[str, Any]],
    prompt_token_count: int,
    elapsed_seconds: float,
    reason: str,
    affected_block_ids: list[str],
) -> None:
    block_ids = [str(block["block_id"]) for block in blocks]
    _emit_translation_event(
        release_id=release_id,
        run_id=run_id,
        event_type="pass2.batch_fallback",
        chapter_number=chapter_number,
        severity="warning",
        message=f"Pass2 batch {batch_index} fallback: {reason}",
        payload={
            "pass_name": "pass2",
            "batch_index": batch_index,
            "block_count": len(blocks),
            "block_ids": block_ids,
            "prompt_token_count": prompt_token_count,
            "elapsed_seconds": elapsed_seconds,
            "reason": reason,
            "affected_block_ids": affected_block_ids,
        },
    )


def _process_pass2_batch_work_unit(
    blocks: list[dict[str, Any]],
    *,
    batch_items: list[dict[str, Any]],
    batch_index: int,
    pass2_batch_prompt_template: str,
    pass2_prompt_template: str,
    analyst_model: str,
    client: LLMClient,
    placeholders_by_block: dict[str, list[PlaceholderEntry]],
    bundles_by_block: dict[str, Any] | None,
    release_id: str,
    run_id: str,
    chapter_number: int,
    config: AppConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    block_ids = [str(block["block_id"]) for block in blocks]
    prompt = render_pass2_batch_prompt(
        prompt_template=pass2_batch_prompt_template,
        batch_items=batch_items,
    )
    prompt_token_count = ensure_pass2_batch_prompt_within_budget(
        prompt,
        model_name=analyst_model,
        config=config,
        chapter_number=chapter_number,
    )
    _emit_translation_event(
        release_id=release_id,
        run_id=run_id,
        event_type="pass2.batch_started",
        chapter_number=chapter_number,
        message=f"Pass2 batch {batch_index} started",
        payload={
            "pass_name": "pass2",
            "batch_index": batch_index,
            "block_count": len(blocks),
            "block_ids": block_ids,
            "prompt_token_count": prompt_token_count,
        },
    )
    started = time.perf_counter()
    response = client.generate_text(model_name=analyst_model, prompt=prompt)
    elapsed = time.perf_counter() - started

    affected_block_ids: list[str] = []
    fallback_reason = ""
    try:
        corrected_by_block = parse_pass2_batch_response(
            response,
            expected_block_ids=block_ids,
            drafts_by_block_id={str(item["block_id"]): str(item["draft_text"]) for item in batch_items},
            prompt_token_count=prompt_token_count,
        )
    except Pass2BatchResponseError as exc:
        corrected_by_block = exc.partial_outputs or {}
        affected_block_ids = exc.affected_block_ids
        fallback_reason = exc.reason

    block_results_by_id: dict[str, dict[str, Any]] = {}
    structure_checks_by_id: dict[str, list[dict[str, Any]]] = {}
    fidelity_checks_by_id: dict[str, dict[str, Any]] = {}
    affected_set = set(affected_block_ids)
    for block in blocks:
        block_id = str(block["block_id"])
        if block_id in affected_set:
            continue
        if block_id not in corrected_by_block:
            affected_block_ids.append(block_id)
            affected_set.add(block_id)
            fallback_reason = fallback_reason or "missing_block_output"
            continue
        try:
            block_result, structure_checks, fidelity_check = _finalize_pass2_normal_block(
                block,
                corrected_text=corrected_by_block[block_id],
                placeholders_by_block=placeholders_by_block,
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                emit_failure_events=False,
            )
        except Pass2ValidationRetryableError as exc:
            affected_block_ids.append(block_id)
            affected_set.add(block_id)
            fallback_reason = fallback_reason or exc.reason
            continue
        block_results_by_id[block_id] = block_result
        structure_checks_by_id[block_id] = structure_checks
        fidelity_checks_by_id[block_id] = fidelity_check

    if affected_block_ids:
        _emit_pass2_batch_fallback_event(
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            batch_index=batch_index,
            blocks=blocks,
            prompt_token_count=prompt_token_count,
            elapsed_seconds=elapsed,
            reason=fallback_reason or "batch_validation_failed",
            affected_block_ids=affected_block_ids,
        )
        for block in blocks:
            block_id = str(block["block_id"])
            if block_id not in affected_set:
                continue
            block_result, structure_checks, fidelity_check = _process_pass2_block(
                block,
                pass2_prompt_template=pass2_prompt_template,
                analyst_model=analyst_model,
                client=client,
                placeholders_by_block=placeholders_by_block,
                bundles_by_block=bundles_by_block,
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                config=config,
            )
            block_results_by_id[block_id] = block_result
            structure_checks_by_id[block_id] = structure_checks
            fidelity_checks_by_id[block_id] = fidelity_check

    _emit_translation_event(
        release_id=release_id,
        run_id=run_id,
        event_type="pass2.batch_completed",
        chapter_number=chapter_number,
        message=f"Pass2 batch {batch_index} completed",
        payload={
            "pass_name": "pass2",
            "batch_index": batch_index,
            "block_count": len(blocks),
            "block_ids": block_ids,
            "prompt_token_count": prompt_token_count,
            "elapsed_seconds": time.perf_counter() - started,
        },
    )

    ordered_blocks = [block_results_by_id[str(block["block_id"])] for block in blocks]
    ordered_structure_checks: list[dict[str, Any]] = []
    ordered_fidelity_checks: list[dict[str, Any]] = []
    for block in blocks:
        block_id = str(block["block_id"])
        ordered_structure_checks.extend(structure_checks_by_id[block_id])
        ordered_fidelity_checks.append(fidelity_checks_by_id[block_id])

    return (
        ordered_blocks,
        ordered_structure_checks,
        ordered_fidelity_checks,
        {
            "batches_attempted": 1,
            "batch_fallbacks": 1 if affected_block_ids else 0,
            "batch_fallback_blocks": len(set(affected_block_ids)),
        },
    )


def _process_pass2_work_unit(
    unit: dict[str, Any],
    *,
    batch_index: int,
    pass2_batch_prompt_template: str,
    pass2_prompt_template: str,
    analyst_model: str,
    client: LLMClient,
    placeholders_by_block: dict[str, list[PlaceholderEntry]],
    bundles_by_block: dict[str, Any] | None,
    release_id: str,
    run_id: str,
    chapter_number: int,
    config: AppConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    blocks = list(unit["blocks"])
    if unit["kind"] == "batch":
        return _process_pass2_batch_work_unit(
            blocks,
            batch_items=list(unit["batch_items"]),
            batch_index=batch_index,
            pass2_batch_prompt_template=pass2_batch_prompt_template,
            pass2_prompt_template=pass2_prompt_template,
            analyst_model=analyst_model,
            client=client,
            placeholders_by_block=placeholders_by_block,
            bundles_by_block=bundles_by_block,
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            config=config,
        )

    block_result, structure_checks, fidelity_check = _process_pass2_block(
        blocks[0],
        pass2_prompt_template=pass2_prompt_template,
        analyst_model=analyst_model,
        client=client,
        placeholders_by_block=placeholders_by_block,
        bundles_by_block=bundles_by_block,
        release_id=release_id,
        run_id=run_id,
        chapter_number=chapter_number,
        config=config,
    )
    return [block_result], structure_checks, [fidelity_check], {
        "batches_attempted": 0,
        "batch_fallbacks": 0,
        "batch_fallback_blocks": 0,
    }


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

    bundles_by_block = load_bundles_for_chapter(
        release_id=release_id,
        chapter_number=chapter_number,
        config=config_obj,
        project_root=project_root,
        warning_callback=lambda payload: _emit_bundle_context_missing_event(
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            pass_name="pass2",
            payload=payload,
        ),
    )

    run_root = paths.release_root / "runs" / run_id
    translation_dir = run_root / "translation" / f"chapter-{chapter_number}"
    validation_dir = run_root / "validation" / f"chapter-{chapter_number}"
    pass1_artifact_path = translation_dir / "pass1.json"
    pass2_artifact_path = translation_dir / "pass2.json"
    structure_report_path = validation_dir / "structure.json"
    fidelity_report_path = validation_dir / "fidelity.json"
    chapter_report_path = validation_dir / "chapter.json"

    pass2_prompt = load_prompt("translate_pass2.txt")
    pass2_batch_prompt = load_prompt("translate_pass2_batch.txt")
    analyst_model = config_obj.models.analyst_name
    client = _build_llm_client(config_obj, llm_client)
    usage_before = capture_usage_snapshot(client)

    conn = open_connection(paths.db_path)
    ensure_checkpoint_schema(conn)

    packet_version_hash = _latest_packet_version_hash(
        conn,
        release_id=release_id,
        chapter_number=chapter_number,
    )

    try:
        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="pass2.started",
            chapter_number=chapter_number,
            message=f"Pass2 started for chapter {chapter_number}",
            payload={"pass_name": "pass2", "model_name": analyst_model},
        )
        pass1_payload = _read_json(pass1_artifact_path)
        pass1_blocks = list(pass1_payload.get("blocks", []))
        if pass1_payload.get("status") != "success" or any(
            not isinstance(block, dict) or block.get("status") == "failed"
            for block in pass1_blocks
        ):
            raise RuntimeError("Pass 1 is incomplete; Pass 2 will not run.")

        pass2_checkpoint = load_checkpoint(
            conn,
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            pass_name="pass2",
            source_hash=source_hash,
            prompt_version=pass2_prompt.version,
            packet_version_hash=packet_version_hash,
        )

        cached_payload: dict[str, Any] | None = None
        reusable_cached_blocks: dict[str, dict[str, Any]] = {}
        if (
            not force
            and pass2_checkpoint is not None
            and Path(pass2_checkpoint.artifact_path).exists()
        ):
            cached_payload = _read_json(Path(pass2_checkpoint.artifact_path))
            reusable_cached_blocks = _reusable_pass2_blocks(
                pass1_blocks,
                cached_payload.get("blocks"),
            )

        if (
            not force
            and pass2_checkpoint is not None
            and pass2_checkpoint.status == "success"
            and cached_payload is not None
            and len(reusable_cached_blocks) == len(pass1_blocks)
        ):
            pass2_blocks = list(cached_payload.get("blocks", []))
            pass2_structure_checks = list(cached_payload.get("structure_validation", []))
            fidelity_checks = list(cached_payload.get("fidelity_validation", []))
            pass2_payload = cached_payload
            logger.info("Chapter {} pass2: using cached artifact", chapter_number)
            _emit_translation_event(
                release_id=release_id,
                run_id=run_id,
                event_type="pass2.cached",
                chapter_number=chapter_number,
                message=f"Pass2 cache hit for chapter {chapter_number}",
                payload={
                    "pass_name": "pass2",
                    "artifact_path": pass2_checkpoint.artifact_path,
                    "status": pass2_checkpoint.status,
                },
            )
        else:
            pass2_blocks = [
                reusable_cached_blocks[str(block["block_id"])]
                for block in pass1_blocks
                if str(block["block_id"]) in reusable_cached_blocks
            ]
            pass2_structure_checks = []
            fidelity_checks = []
            pass2_batching: dict[str, Any] = {
                "enabled": config_obj.translation.pass2_batch_max_blocks > 1,
                "max_blocks": config_obj.translation.pass2_batch_max_blocks,
                "batches_attempted": 0,
                "batch_fallbacks": 0,
                "batch_fallback_blocks": 0,
                "batch_prompt_version": pass2_batch_prompt.version,
            }

            blocks_to_process: list[dict[str, Any]] = []
            for block in pass1_blocks:
                if str(block["block_id"]) in reusable_cached_blocks:
                    continue
                blocks_to_process.append(block)

            if blocks_to_process:
                concurrency = config_obj.translation.pass2_concurrency
                work_units = _pack_pass2_work_units(
                    blocks_to_process,
                    pass2_batch_prompt_template=pass2_batch_prompt.template,
                    analyst_model=analyst_model,
                    bundles_by_block=bundles_by_block,
                    config=config_obj,
                    chapter_number=chapter_number,
                )
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    fut_map: dict[Future, int] = {}
                    batch_number = 0
                    batch_numbers_by_index: dict[int, int] = {}
                    for i, unit in enumerate(work_units):
                        if unit["kind"] == "batch":
                            batch_number += 1
                            batch_numbers_by_index[i] = batch_number
                        else:
                            batch_numbers_by_index[i] = 0
                        fut = executor.submit(
                            _process_pass2_work_unit,
                            unit,
                            batch_index=batch_numbers_by_index[i],
                            pass2_batch_prompt_template=pass2_batch_prompt.template,
                            pass2_prompt_template=pass2_prompt.template,
                            analyst_model=analyst_model,
                            client=client,
                            placeholders_by_block=placeholders_by_block,
                            bundles_by_block=bundles_by_block,
                            release_id=release_id,
                            run_id=run_id,
                            chapter_number=chapter_number,
                            config=config_obj,
                        )
                        fut_map[fut] = i

                    results: dict[int, tuple] = {}
                    for future in as_completed(fut_map):
                        idx = fut_map[future]
                        try:
                            results[idx] = future.result()
                        except Exception as exc:
                            block_id = str(work_units[idx]["blocks"][0].get("block_id", ""))
                            _emit_translation_event(
                                release_id=release_id,
                                run_id=run_id,
                                event_type="pass2.failed",
                                chapter_number=chapter_number,
                                block_id=block_id,
                                severity="error",
                                message=f"Pass2 worker failed for {block_id}: {exc}",
                                payload={"pass_name": "pass2", "reason": str(exc)},
                            )
                            raise

                for idx in sorted(results):
                    block_results, struct_checks, unit_fidelity_checks, unit_stats = results[idx]
                    pass2_blocks.extend(block_results)
                    pass2_structure_checks.extend(struct_checks)
                    fidelity_checks.extend(unit_fidelity_checks)
                    pass2_batching["batches_attempted"] += int(unit_stats["batches_attempted"])
                    pass2_batching["batch_fallbacks"] += int(unit_stats["batch_fallbacks"])
                    pass2_batching["batch_fallback_blocks"] += int(unit_stats["batch_fallback_blocks"])

            pass2_by_id = {str(block["block_id"]): block for block in pass2_blocks}
            pass2_blocks = [pass2_by_id[str(block["block_id"])] for block in pass1_blocks]

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
                "batch_prompt_version": pass2_batch_prompt.version,
                "source_hash": source_hash,
                "blocks": pass2_blocks,
                "structure_validation": pass2_structure_checks,
                "fidelity_validation": fidelity_checks,
                "batching": pass2_batching,
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
                packet_version_hash=packet_version_hash,
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
            failed_count = sum(
                1 for check in [*pass2_structure_checks, *fidelity_checks] if check["status"] == "failed"
            )
            _emit_translation_event(
                release_id=release_id,
                run_id=run_id,
                event_type="pass2.failed",
                chapter_number=chapter_number,
                severity="error",
                message=f"Pass2 validation failed for chapter {chapter_number}",
                payload={"pass_name": "pass2", "failed_count": failed_count},
            )
            raise RuntimeError("Pass 2 failed validation.")

        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="pass2.completed",
            chapter_number=chapter_number,
            message=f"Pass2 completed for chapter {chapter_number}",
            payload={
                "pass_name": "pass2",
                "status": "success",
                "artifact_path": str(pass2_artifact_path),
            },
        )
        return {
            "status": "success",
            "pass2_artifact": str(pass2_artifact_path),
            "blocks": pass2_blocks,
            **usage_payload_delta(client, usage_before),
        }
    except Exception as exc:
        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="pass2.failed",
            chapter_number=chapter_number,
            severity="error",
            message=f"Pass2 failed for chapter {chapter_number}: {exc}",
            payload={"pass_name": "pass2", "reason": str(exc)},
        )
        raise
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
    force: bool = False,
) -> dict[str, Any]:
    config_obj = config or load_config()
    if not config_obj.translation.pass3_default:
        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="pass3.skipped",
            chapter_number=chapter_number,
            message=f"Pass3 skipped for chapter {chapter_number}: disabled",
            payload={"pass_name": "pass3", "reason": "disabled"},
        )
        return {"status": "skipped", "pass3_artifact": None}

    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    run_root = paths.release_root / "runs" / run_id
    translation_dir = run_root / "translation" / f"chapter-{chapter_number}"
    pass2_artifact_path = translation_dir / "pass2.json"
    pass3_artifact_path = translation_dir / "pass3.json"

    if not pass2_artifact_path.exists():
        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="pass3.skipped",
            chapter_number=chapter_number,
            severity="warning",
            message=f"Pass3 skipped for chapter {chapter_number}: pass2 artifact missing",
            payload={"pass_name": "pass3", "reason": "missing_pass2_artifact"},
        )
        return {"status": "skipped", "pass3_artifact": None}

    try:
        pass2_payload = _read_json(pass2_artifact_path)
    except Exception as exc:
        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="pass3.failed",
            chapter_number=chapter_number,
            severity="error",
            message=f"Pass3 failed for chapter {chapter_number}: {exc}",
            payload={"pass_name": "pass3", "reason": str(exc)},
        )
        raise
    pass2_blocks = list(pass2_payload.get("blocks", []))

    if not pass2_blocks:
        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="pass3.skipped",
            chapter_number=chapter_number,
            severity="warning",
            message=f"Pass3 skipped for chapter {chapter_number}: pass2 has no blocks",
            payload={"pass_name": "pass3", "reason": "empty_pass2_blocks"},
        )
        return {"status": "skipped", "pass3_artifact": None}

    pass3_prompt = load_prompt("translate_pass3.txt")
    model_name = config_obj.models.analyst_name
    client = _build_llm_client(config_obj, llm_client)
    usage_before = capture_usage_snapshot(client)
    source_hash = str(pass2_payload.get("source_hash", ""))

    conn = open_connection(paths.db_path)
    ensure_checkpoint_schema(conn)

    packet_version_hash = _latest_packet_version_hash(
        conn,
        release_id=release_id,
        chapter_number=chapter_number,
    )

    try:
        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="pass3.started",
            chapter_number=chapter_number,
            message=f"Pass3 started for chapter {chapter_number}",
            payload={"pass_name": "pass3", "model_name": model_name},
        )
        pass3_checkpoint = load_checkpoint(
            conn,
            release_id=release_id,
            run_id=run_id,
            chapter_number=chapter_number,
            pass_name="pass3",
            source_hash=source_hash,
            prompt_version=pass3_prompt.version,
            packet_version_hash=packet_version_hash,
        )

        if (
            not force
            and pass3_checkpoint is not None
            and pass3_checkpoint.status == "success"
            and Path(pass3_checkpoint.artifact_path).exists()
        ):
            logger.info("Chapter {} pass3: using cached artifact", chapter_number)
            _emit_translation_event(
                release_id=release_id,
                run_id=run_id,
                event_type="pass3.cached",
                chapter_number=chapter_number,
                message=f"Pass3 cache hit for chapter {chapter_number}",
                payload={
                    "pass_name": "pass3",
                    "artifact_path": pass3_checkpoint.artifact_path,
                    "status": pass3_checkpoint.status,
                },
            )
            _emit_translation_event(
                release_id=release_id,
                run_id=run_id,
                event_type="pass3.completed",
                chapter_number=chapter_number,
                message=f"Pass3 completed for chapter {chapter_number} from cache",
                payload={
                    "pass_name": "pass3",
                    "status": "cached",
                    "artifact_path": pass3_checkpoint.artifact_path,
                },
            )
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
            warning_callback=lambda payload: _emit_bundle_context_missing_event(
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                pass_name="pass3",
                payload=payload,
            ),
        )

        threshold_high = config_obj.translation.risk_threshold_high
        pass3_blocks: list[dict[str, Any]] = []
        risk_classifications: list[dict[str, Any]] = []
        pass3_integrity_checks: list[dict[str, Any]] = []

        for block in pass2_blocks:
            source_text = str(block["source_text_zh"])
            pass2_output = str(block["output_text_en"])
            block_id = str(block["block_id"])

            bundle3 = bundles_by_block.get(block_id) if bundles_by_block else None
            if bundle3 is not None:
                risk = classify_paragraph_risk_from_text(
                    source_text=source_text,
                    pass2_text=pass2_output,
                    idiom_count=len(bundle3.matched_idioms),
                    title_count=_count_title_honorific_glossary_entries(bundle3),
                    has_reveal_gated_relationship=_has_reveal_gated_relationship(bundle3),
                    distinct_entity_count=len(bundle3.alias_resolutions),
                    threshold_high=threshold_high,
                )
            else:
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
                _emit_translation_event(
                    release_id=release_id,
                    run_id=run_id,
                    event_type="pass3.skipped",
                    chapter_number=chapter_number,
                    block_id=block_id,
                    severity="warning",
                    message=f"Pass3 skipped high-risk block {block_id}",
                    payload={"pass_name": "pass3", "reason": "high_risk", "risk_score": risk.risk_score},
                )
                continue

            bundle3 = bundles_by_block.get(block_id) if bundles_by_block else None
            pass3_context = format_bundle_for_pass3(bundle3)
            glossary_target_terms = extract_glossary_target_terms_for_pass3(bundle3)

            polished_text = translate_pass3(
                client=client,
                model_name=model_name,
                prompt_template=pass3_prompt.template,
                source_text=source_text,
                pass2_output=pass2_output,
                glossary_text=pass3_context["glossary"],
                alias_resolutions=pass3_context["alias_resolutions"],
                matched_idioms=pass3_context["matched_idioms"],
                relationship_constraints=pass3_context["relationship_constraints"],
                config=config_obj,
                chapter_number=chapter_number,
            )

            integrity = validate_pass3_integrity(
                source_text=source_text,
                pass2_output=pass2_output,
                pass3_output=polished_text,
                glossary_terms=glossary_target_terms,
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
                _emit_translation_event(
                    release_id=release_id,
                    run_id=run_id,
                    event_type="pass3.skipped",
                    chapter_number=chapter_number,
                    block_id=block_id,
                    severity="warning",
                    message=f"Pass3 rejected by integrity validation for {block_id}",
                    payload={
                        "pass_name": "pass3",
                        "reason": "integrity_rejection",
                        "errors": integrity.errors,
                        "warnings": integrity.warnings,
                    },
                )

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
            packet_version_hash=packet_version_hash,
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

        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="pass3.completed",
            chapter_number=chapter_number,
            message=f"Pass3 completed for chapter {chapter_number}",
            payload={
                "pass_name": "pass3",
                "status": "success",
                "artifact_path": str(pass3_artifact_path),
            },
        )
        return {
            "status": "success",
            "pass3_artifact": str(pass3_artifact_path),
            **usage_payload_delta(client, usage_before),
        }
    except Exception as exc:
        _emit_translation_event(
            release_id=release_id,
            run_id=run_id,
            event_type="pass3.failed",
            chapter_number=chapter_number,
            severity="error",
            message=f"Pass3 failed for chapter {chapter_number}: {exc}",
            payload={"pass_name": "pass3", "reason": str(exc)},
        )
        raise
    finally:
        conn.close()
