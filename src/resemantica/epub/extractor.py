from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

from resemantica.chapters.manifest import write_chapter_manifest
from resemantica.db.extraction_repo import record_extraction_metadata
from resemantica.db.sqlite import open_connection
from resemantica.epub.models import ChapterDocument, ChapterParseResult, RoundTripResult
from resemantica.epub.parser import parse_chapters
from resemantica.epub.rebuild import rebuild_epub
from resemantica.epub.validators import validate_extraction
from resemantica.orchestration.events import emit_event
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.utils import _write_json

_XHTML_MEDIA_TYPES = {
    "application/xhtml+xml",
    "application/x-dtbncx+xml",
}


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _reset_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _discover_opf(unpacked_dir: Path) -> Path:
    container = unpacked_dir / "META-INF" / "container.xml"
    tree = ET.parse(container)
    root = tree.getroot()
    rootfiles = [node for node in root.iter() if _local_name(node.tag) == "rootfile"]
    if not rootfiles:
        raise ValueError("OPF rootfile not found in META-INF/container.xml")
    full_path = rootfiles[0].attrib.get("full-path")
    if not full_path:
        raise ValueError("rootfile missing full-path attribute")
    return unpacked_dir / full_path


def _manifest_and_spine(opf_path: Path) -> tuple[dict[str, dict[str, str]], list[str]]:
    tree = ET.parse(opf_path)
    root = tree.getroot()

    manifest: dict[str, dict[str, str]] = {}
    spine_ids: list[str] = []

    for node in root.iter():
        tag_name = _local_name(node.tag)
        if tag_name == "item":
            item_id = node.attrib.get("id")
            href = node.attrib.get("href")
            media_type = node.attrib.get("media-type", "")
            if item_id and href:
                manifest[item_id] = {"href": href, "media_type": media_type}
        elif tag_name == "itemref":
            idref = node.attrib.get("idref")
            if idref:
                spine_ids.append(idref)

    return manifest, spine_ids


def _chapter_documents(opf_path: Path) -> list[ChapterDocument]:
    manifest, spine_ids = _manifest_and_spine(opf_path)
    opf_dir = opf_path.parent

    chapter_documents: list[ChapterDocument] = []
    chapter_number = 0
    for item_id in spine_ids:
        item = manifest.get(item_id)
        if item is None:
            continue
        href = item["href"]
        media_type = item["media_type"]
        suffix = Path(href).suffix.lower()
        if media_type not in _XHTML_MEDIA_TYPES and suffix not in {".xhtml", ".html", ".htm"}:
            continue

        chapter_number += 1
        chapter_documents.append(
            ChapterDocument(
                chapter_number=chapter_number,
                manifest_id=item_id,
                href=href,
                absolute_path=(opf_dir / href).resolve(),
            )
        )

    return chapter_documents


def _write_chapter_artifacts(
    chapter_results: Iterable[ChapterParseResult],
    chapter_dir: Path,
    placeholder_dir: Path,
) -> None:
    for chapter in chapter_results:
        chapter_payload = {
            "chapter_id": chapter.chapter_id,
            "chapter_number": chapter.chapter_number,
            "source_document_path": chapter.source_document_path,
            "chapter_source_hash": chapter.chapter_source_hash,
            "schema_version": 1,
            "records": [record.to_json_dict() for record in chapter.records],
        }
        chapter_path = chapter_dir / f"chapter-{chapter.chapter_number}.json"
        _write_json(chapter_path, chapter_payload)

        placeholder_payload = {
            "chapter_number": chapter.chapter_number,
            "chapter_source_hash": chapter.chapter_source_hash,
            "schema_version": 1,
            "blocks": {
                block_id: [entry.to_json_dict() for entry in entries]
                for block_id, entries in chapter.placeholders_by_block.items()
            },
        }
        placeholder_path = placeholder_dir / f"chapter-{chapter.chapter_number}.json"
        _write_json(placeholder_path, placeholder_payload)


def extract_epub(
    input_path: str | Path,
    release_id: str,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    run_id: str = "epub-extract",
) -> RoundTripResult:
    input_epub = Path(input_path).resolve()
    if not input_epub.exists():
        raise FileNotFoundError(f"Input EPUB not found: {input_epub}")

    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)

    _reset_directory(paths.unpacked_dir)
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
    paths.extracted_reports_dir.mkdir(parents=True, exist_ok=True)
    paths.extracted_placeholders_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(input_epub, "r") as source_archive:
        source_archive.extractall(paths.unpacked_dir)

    opf_path = _discover_opf(paths.unpacked_dir)
    chapter_documents = _chapter_documents(opf_path)

    def placeholder_map_ref(chapter_number: int) -> str:
        return str(
            (
                paths.extracted_placeholders_dir / f"chapter-{chapter_number}.json"
            ).as_posix()
        )

    chapter_results = []
    for chapter_doc in chapter_documents:
        emit_event(
            run_id=run_id,
            release_id=release_id,
            event_type="epub.extraction.chapter_started",
            stage_name="epub-extract",
            chapter_number=chapter_doc.chapter_number,
            message=f"Extracting chapter {chapter_doc.chapter_number}",
        )
        try:
            result = parse_chapters([chapter_doc], placeholder_map_ref_builder=placeholder_map_ref)
            chapter_results.extend(result)
            emit_event(
                run_id=run_id,
                release_id=release_id,
                event_type="epub.extraction.chapter_completed",
                stage_name="epub-extract",
                chapter_number=chapter_doc.chapter_number,
                message=f"Extracted chapter {chapter_doc.chapter_number}",
            )
        except Exception as exc:
            emit_event(
                run_id=run_id,
                release_id=release_id,
                event_type="epub.extraction.chapter_skipped",
                stage_name="epub-extract",
                chapter_number=chapter_doc.chapter_number,
                severity="warning",
                message=f"Skipped chapter {chapter_doc.chapter_number}: {exc}",
            )

    emit_event(
        run_id=run_id,
        release_id=release_id,
        event_type="epub.extraction.completed",
        stage_name="epub-extract",
        message=f"Extraction completed: {len(chapter_results)} chapters",
    )

    _write_chapter_artifacts(
        chapter_results=chapter_results,
        chapter_dir=paths.extracted_chapters_dir,
        placeholder_dir=paths.extracted_placeholders_dir,
    )
    write_chapter_manifest(paths)
    conn = open_connection(paths.db_path)
    try:
        for chapter_result in chapter_results:
            record_extraction_metadata(
                conn,
                release_id=release_id,
                run_id=run_id,
                chapter_result=chapter_result,
            )
    finally:
        conn.close()

    validation_report = validate_extraction(release_id, chapter_results)
    validation_report_path = paths.extracted_reports_dir / "xhtml-validation.json"
    _write_json(validation_report_path, validation_report)

    rebuilt_path = rebuild_epub(paths.unpacked_dir, paths.rebuilt_epub_path)

    return RoundTripResult(
        release_id=release_id,
        release_root=paths.release_root,
        rebuilt_epub_path=rebuilt_path,
        validation_report_path=validation_report_path,
        chapter_results=chapter_results,
    )
