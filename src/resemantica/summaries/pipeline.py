from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.db.glossary_repo import ensure_glossary_schema, list_locked_entries
from resemantica.db.sqlite import open_connection
from resemantica.db.summary_repo import (
    ensure_summary_schema,
    get_validated_summary,
    is_non_story_chapter,
    list_validated_summaries,
    save_derived_summary,
    save_validated_summary,
)
from resemantica.llm.client import LLMClient
from resemantica.llm.budget import PromptBudgetError
from resemantica.llm.prompts import load_prompt
from resemantica.orchestration.events import emit_event
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.summaries.derivation import (
    build_story_so_far,
    derive_english_summary,
    hash_locked_glossary,
    hash_validated_summary,
)
from resemantica.summaries.generator import generate_chapter_summary
from resemantica.summaries.validators import validate_chinese_summary_content

_CHAPTER_FILE_RE = re.compile(r"chapter-(\d+)\.json$")
_STAGE_NAME = "preprocess-summaries"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid JSON root in {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _chapter_number_from_path(path: Path) -> int:
    match = _CHAPTER_FILE_RE.search(path.name)
    if match is None:
        raise ValueError(f"Unexpected chapter filename: {path.name}")
    return int(match.group(1))


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


def _build_llm_client(config: AppConfig, llm_client: LLMClient | None) -> LLMClient:
    if llm_client is not None:
        return llm_client
    return LLMClient(
        base_url=config.llm.base_url,
        timeout_seconds=config.llm.timeout_seconds,
        max_retries=config.llm.max_retries,
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
    ensure_glossary_schema(conn)
    ensure_summary_schema(conn)

    chapter_results: list[dict[str, Any]] = []

    try:
        for chapter_file in chapter_files:
            chapter_payload = _read_json(chapter_file)
            chapter_number = int(chapter_payload["chapter_number"])
            chapter_source_hash = str(chapter_payload["chapter_source_hash"])
            _emit(run_id, release_id, f"{_STAGE_NAME}.chapter_started", chapter_number=chapter_number)

            source_doc = str(chapter_payload.get("source_document_path", ""))
            if _exclude_compiled and any(p.search(source_doc) for p in _exclude_compiled):
                print(f"  SKIP: chapter {chapter_number} ({source_doc}) matches exclude pattern")
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.chapter_skipped",
                    chapter_number=chapter_number,
                    reason="exclude_pattern",
                )
                chapter_results.append(
                    {
                        "chapter_number": chapter_number,
                        "chapter_source_hash": chapter_source_hash,
                        "status": "skipped",
                    }
                )
                continue

            source_text_zh = _collect_source_text(chapter_payload)
            locked_glossary = list_locked_entries(conn, release_id=release_id)

            generated = generate_chapter_summary(
                conn=conn,
                release_id=release_id,
                run_id=run_id,
                chapter_number=chapter_number,
                chapter_source_hash=chapter_source_hash,
                source_text_zh=source_text_zh,
                locked_glossary=locked_glossary,
                llm_client=client,
                model_name=config_obj.models.analyst_name,
                prompt_template=prompt_structured.template,
                prompt_version=prompt_structured.version,
                config=config_obj,
                cache_root=paths.release_root / "cache" / "llm",
            )
            if generated is None:
                if is_non_story_chapter(conn, release_id=release_id, chapter_number=chapter_number):
                    print(f"  SKIP: chapter {chapter_number}: non-story chapter flagged")
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.chapter_skipped",
                        chapter_number=chapter_number,
                        reason="non_story_chapter",
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
                    print(f"  WARN: chapter {chapter_number}: summary generation failed, skipping")
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.chapter_skipped",
                        chapter_number=chapter_number,
                        reason="generation_failed",
                    )
                    chapter_results.append(
                        {
                            "chapter_number": chapter_number,
                            "chapter_source_hash": chapter_source_hash,
                            "status": "skipped",
                        }
                    )
                continue
            _emit(run_id, release_id, f"{_STAGE_NAME}.draft_generated", chapter_number=chapter_number)
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.validation_completed",
                chapter_number=chapter_number,
                status=generated.validation.status,
            )

            try:
                llm_validation_flags = validate_chinese_summary_content(
                    llm_client=client,
                    model_name=config_obj.models.analyst_name,
                    prompt_template=prompt_validate.template,
                    source_text_zh=source_text_zh,
                    structured_summary=generated.structured_summary,
                    locked_glossary=locked_glossary,
                    config=config_obj,
                )
            except PromptBudgetError:
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.chapter_skipped",
                    chapter_number=chapter_number,
                    reason="prompt_budget_exceeded",
                )
                chapter_results.append(
                    {
                        "chapter_number": chapter_number,
                        "chapter_source_hash": chapter_source_hash,
                        "status": "skipped",
                        "reason": "prompt_budget_exceeded",
                    }
                )
                continue

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
                story_text = previous_story.content_zh.rstrip("\n") + "\n" + f"第{chapter_number}章：{last_short.content_zh.strip()}"
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
            chapter_summary_en = derive_english_summary(
                llm_client=client,
                model_name=config_obj.models.translator_name,
                prompt_template=prompt_en.template,
                source_text_zh=generated.short_record.content_zh,
                locked_glossary=locked_glossary,
            )
            chapter_en_record = save_derived_summary(
                conn,
                release_id=release_id,
                chapter_number=chapter_number,
                summary_type="chapter_summary_en_short",
                content_en=chapter_summary_en,
                source_summary_id=generated.short_record.summary_id,
                source_summary_hash=hash_validated_summary(generated.short_record),
                glossary_version_hash=glossary_version_hash,
                model_name=config_obj.models.translator_name,
                prompt_version=prompt_en.version,
                run_id=run_id,
            )

            story_so_far_en = derive_english_summary(
                llm_client=client,
                model_name=config_obj.models.translator_name,
                prompt_template=prompt_en.template,
                source_text_zh=story_record.content_zh,
                locked_glossary=locked_glossary,
            )
            story_en_record = save_derived_summary(
                conn,
                release_id=release_id,
                chapter_number=chapter_number,
                summary_type="story_so_far_en",
                content_en=story_so_far_en,
                source_summary_id=story_record.summary_id,
                source_summary_hash=hash_validated_summary(story_record),
                glossary_version_hash=glossary_version_hash,
                model_name=config_obj.models.translator_name,
                prompt_version=prompt_en.version,
                run_id=run_id,
            )

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
                    "llm_validation_flags": llm_validation_flags,
                },
            )
            _write_json(
                en_artifact,
                {
                    "release_id": release_id,
                    "run_id": run_id,
                    "chapter_number": chapter_number,
                    "schema_version": 1,
                    "derived": {
                        "chapter_summary_en_short": chapter_en_record.to_json_dict(),
                        "story_so_far_en": story_en_record.to_json_dict(),
                    },
                },
            )

            chapter_results.append(
                {
                    "chapter_number": chapter_number,
                    "chapter_source_hash": chapter_source_hash,
                    "zh_artifact": str(zh_artifact),
                    "en_artifact": str(en_artifact),
                }
            )
            _emit(run_id, release_id, f"{_STAGE_NAME}.chapter_completed", chapter_number=chapter_number)
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
    )
    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "chapters_processed": processed_count,
        "chapter_artifacts": chapter_results,
    }
