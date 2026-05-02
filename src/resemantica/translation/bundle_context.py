from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from loguru import logger

from resemantica.db.packet_repo import get_latest_packet_metadata
from resemantica.db.sqlite import open_connection
from resemantica.packets.models import ParagraphBundle
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.utils import _read_json


def load_bundles_for_chapter(
    release_id: str,
    chapter_number: int,
    config: AppConfig | None = None,
    project_root: Path | None = None,
) -> dict[str, ParagraphBundle] | None:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    conn = open_connection(paths.db_path)
    try:
        metadata = get_latest_packet_metadata(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
        )
    except sqlite3.OperationalError:
        logger.warning("packet_metadata table not found, continuing without bundle context")
        return None
    finally:
        conn.close()

    if metadata is None:
        logger.warning("No packet metadata found for chapter {}", chapter_number)
        return None

    bundle_path = Path(metadata.bundle_path)
    if not bundle_path.exists():
        logger.warning("Bundle file not found: {}", bundle_path)
        return None

    payload = _read_json(bundle_path)
    raw_bundles = payload.get("bundles")
    if not isinstance(raw_bundles, list) or not raw_bundles:
        return None

    bundles: dict[str, ParagraphBundle] = {}
    for raw in raw_bundles:
        if not isinstance(raw, dict):
            continue
        bundle = ParagraphBundle(**raw)
        bundles[bundle.block_id] = bundle

    return bundles


def _format_glossary_entry(entry: dict[str, Any]) -> str:
    source = str(entry.get("source_term", ""))
    target = str(entry.get("target_term", ""))
    category = str(entry.get("category", ""))
    parts = [source, "\u2192", target]
    if category:
        parts.append(f"({category})")
    return " ".join(parts)


def _format_alias_entry(entry: dict[str, Any]) -> str:
    alias = str(entry.get("alias_text", ""))
    entity = str(entry.get("entity_name", ""))
    return f"{alias} \u2192 {entity}"


def _format_idiom_entry(entry: dict[str, Any]) -> str:
    source = str(entry.get("source_text", ""))
    rendering = str(entry.get("preferred_rendering_en", ""))
    return f"{source} \u2192 {rendering}"


def format_bundle_for_pass1(
    bundle: ParagraphBundle,
) -> dict[str, str]:
    glossary_lines = [_format_glossary_entry(entry) for entry in bundle.matched_glossary_entries]
    alias_lines = [_format_alias_entry(entry) for entry in bundle.alias_resolutions]
    idiom_lines = [_format_idiom_entry(entry) for entry in bundle.matched_idioms]

    return {
        "glossary": "\n".join(glossary_lines),
        "alias_resolutions": "\n".join(alias_lines),
        "matched_idioms": "\n".join(idiom_lines),
        "continuity_notes": "\n\n".join(bundle.continuity_notes),
    }


def format_glossary_for_pass3(
    bundle: ParagraphBundle,
) -> str:
    lines = [_format_glossary_entry(entry) for entry in bundle.matched_glossary_entries]
    return "\n".join(lines)
