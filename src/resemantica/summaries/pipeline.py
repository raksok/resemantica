from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from resemantica.db.glossary_repo import ensure_glossary_schema, list_locked_entries
from resemantica.db.sqlite import open_connection
from resemantica.db.summary_repo import (
    ensure_summary_schema,
    list_validated_summaries,
    save_derived_summary,
    save_validated_summary,
)
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import load_prompt
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.summaries.derivation import (
    build_story_so_far,
    derive_english_summary,
    hash_locked_glossary,
    hash_validated_summary,
)
from resemantica.summaries.generator import generate_chapter_summary

_CHAPTER_FILE_RE = re.compile(r"chapter-(\d+)\.json$")


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
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    chapter_files = sorted(
        paths.extracted_chapters_dir.glob("chapter-*.json"),
        key=_chapter_number_from_path,
    )
    if not chapter_files:
        raise FileNotFoundError(
            f"No extracted chapters found for release {release_id}: {paths.extracted_chapters_dir}"
        )

    client = _build_llm_client(config_obj, llm_client)
    prompt_structured = load_prompt("summary_zh_structured.txt")
    prompt_en = load_prompt("summary_en_derive.txt")

    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    ensure_summary_schema(conn)

    chapter_results: list[dict[str, Any]] = []

    try:
        for chapter_file in chapter_files:
            chapter_payload = _read_json(chapter_file)
            chapter_number = int(chapter_payload["chapter_number"])
            chapter_source_hash = str(chapter_payload["chapter_source_hash"])
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
            )

            short_summaries = list_validated_summaries(
                conn,
                release_id=release_id,
                summary_type="chapter_summary_zh_short",
                max_chapter_number=chapter_number,
            )
            story_text = build_story_so_far(short_summaries=short_summaries)
            story_record = save_validated_summary(
                conn,
                release_id=release_id,
                chapter_number=chapter_number,
                summary_type="story_so_far_zh",
                content_zh=story_text,
                derived_from_chapter_hash=chapter_source_hash,
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
    finally:
        conn.close()

    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "chapters_processed": len(chapter_results),
        "chapter_artifacts": chapter_results,
    }
