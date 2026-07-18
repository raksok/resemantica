from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

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
    warning_callback: Callable[[dict[str, object]], None] | None = None,
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
        if warning_callback is not None:
            warning_callback({"reason": "missing_packet_metadata_table"})
        else:
            logger.warning("packet_metadata table not found, continuing without bundle context")
        return None
    finally:
        conn.close()

    if metadata is None:
        if warning_callback is not None:
            warning_callback({"reason": "missing_packet_metadata"})
        else:
            logger.warning("No packet metadata found for chapter {}", chapter_number)
        return None

    bundle_path = Path(metadata.bundle_path)
    if not bundle_path.exists():
        if warning_callback is not None:
            warning_callback({"reason": "missing_bundle_file", "bundle_path": str(bundle_path)})
        else:
            logger.warning("Bundle file not found: {}", bundle_path)
        return None

    payload = _read_json(bundle_path)
    raw_bundles = payload.get("bundles")
    if not isinstance(raw_bundles, list) or not raw_bundles:
        if warning_callback is not None:
            warning_callback({"reason": "empty_bundle_rows", "bundle_path": str(bundle_path)})
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
    parts = [f"{source} \u2192 {rendering}"]
    meaning_en = str(entry.get("meaning_en", "")).strip()
    meaning_zh = str(entry.get("meaning_zh", "")).strip()
    usage_notes = str(entry.get("usage_notes", "")).strip()
    if meaning_en:
        parts.append(f"meaning_en: {meaning_en}")
    if meaning_zh:
        parts.append(f"meaning_zh: {meaning_zh}")
    if usage_notes:
        parts.append(f"usage_notes: {usage_notes}")
    return " | ".join(parts)


def _format_relationship_entry(entry: dict[str, Any]) -> str:
    relationship_type = str(entry.get("type", "")).strip()
    source = str(entry.get("source_entity_id", "")).strip()
    target = str(entry.get("target_entity_id", "")).strip()
    lore_text = str(entry.get("lore_text", "")).strip()
    masked = bool(entry.get("is_masked_identity", False))

    head = " ".join(part for part in [source, relationship_type, target] if part)
    parts = [head or str(entry.get("relationship_id", ""))]
    if lore_text:
        parts.append(f"lore: {lore_text}")
    if masked:
        parts.append("masked_identity: true")
    return " | ".join(part for part in parts if part)


def _format_section(title: str, lines: list[str] | str) -> str:
    if isinstance(lines, str):
        body = lines.strip()
    else:
        body = "\n".join(line for line in lines if line.strip()).strip()
    if not body:
        return ""
    return f"{title}:\n{body}"


def format_bundle_for_pass1(
    bundle: ParagraphBundle | None,
) -> dict[str, str]:
    if bundle is None:
        return {
            "glossary": "",
            "alias_resolutions": "",
            "matched_idioms": "",
            "continuity_notes": "",
        }

    glossary_lines = [_format_glossary_entry(entry) for entry in bundle.matched_glossary_entries]
    alias_lines = [_format_alias_entry(entry) for entry in bundle.alias_resolutions]
    idiom_lines = [_format_idiom_entry(entry) for entry in bundle.matched_idioms]

    return {
        "glossary": "\n".join(glossary_lines),
        "alias_resolutions": "\n".join(alias_lines),
        "matched_idioms": "\n".join(idiom_lines),
        "continuity_notes": "\n\n".join(bundle.continuity_notes),
    }


def format_bundle_for_pass2(bundle: ParagraphBundle | None) -> dict[str, str]:
    if bundle is None:
        return {
            "glossary": "",
            "alias_resolutions": "",
            "matched_idioms": "",
            "local_relationships": "",
            "continuity_notes": "",
            "retrieval_evidence": "",
        }

    return {
        "glossary": _format_section(
            "TERMINOLOGY",
            [_format_glossary_entry(entry) for entry in bundle.matched_glossary_entries],
        ),
        "alias_resolutions": _format_section(
            "ALIASES",
            [_format_alias_entry(entry) for entry in bundle.alias_resolutions],
        ),
        "matched_idioms": _format_section(
            "IDIOMS",
            [_format_idiom_entry(entry) for entry in bundle.matched_idioms],
        ),
        "local_relationships": _format_section(
            "RELATIONSHIPS",
            [_format_relationship_entry(entry) for entry in bundle.local_relationships],
        ),
        "continuity_notes": _format_section("CONTINUITY", bundle.continuity_notes),
        "retrieval_evidence": _format_section(
            "RETRIEVAL_EVIDENCE",
            bundle.retrieval_evidence_summary,
        ),
    }


def format_bundle_for_pass3(bundle: ParagraphBundle | None) -> dict[str, str]:
    if bundle is None:
        return {
            "glossary": "",
            "alias_resolutions": "",
            "matched_idioms": "",
            "relationship_constraints": "",
        }

    return {
        "glossary": _format_section(
            "TERMINOLOGY TO PRESERVE",
            [_format_glossary_entry(entry) for entry in bundle.matched_glossary_entries],
        ),
        "alias_resolutions": _format_section(
            "ALIASES TO PRESERVE",
            [_format_alias_entry(entry) for entry in bundle.alias_resolutions],
        ),
        "matched_idioms": _format_section(
            "IDIOM RENDERINGS TO PRESERVE",
            [_format_idiom_entry(entry) for entry in bundle.matched_idioms],
        ),
        "relationship_constraints": _format_section(
            "RELATIONSHIP CONSTRAINTS",
            [_format_relationship_entry(entry) for entry in bundle.local_relationships],
        ),
    }


def format_glossary_for_pass3(bundle: ParagraphBundle | None) -> str:
    if bundle is None:
        return ""
    return "\n".join(_format_glossary_entry(entry) for entry in bundle.matched_glossary_entries)


def extract_glossary_target_terms_for_pass3(bundle: ParagraphBundle | None) -> list[str]:
    if bundle is None:
        return []
    terms = {
        str(entry.get("target_term", "")).strip()
        for entry in bundle.matched_glossary_entries
        if str(entry.get("target_term", "")).strip()
    }
    return sorted(terms)
