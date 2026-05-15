from __future__ import annotations

import posixpath
import shutil
import urllib.parse
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from loguru import logger

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.db.sqlite import ensure_schema, open_connection
from resemantica.db.summary_repo import is_non_story_chapter
from resemantica.epub.models import PlaceholderEntry
from resemantica.epub.placeholders import restore_from_placeholders
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.utils import _emit as _emit_shared
from resemantica.utils import _read_json, _write_json

_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "li", "td", "table"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_STAGE_NAME = "epub-rebuild"


def _emit(run_id: str, release_id: str, event_type: str, **kwargs: object) -> None:
    _emit_shared(run_id, release_id, event_type, stage_name=_STAGE_NAME, **kwargs)


@dataclass(slots=True)
class ValidationReport:
    report_id: str
    report_scope: str
    release_id: str
    run_id: str
    chapter_number: int | None
    validation_type: str = "reconstruction"
    status: str = "success"
    severity: str = "info"
    flags: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: str = "1.0"

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChapterRebuildResult:
    chapter_number: int
    source_document_path: str
    xhtml: str
    status: str
    flags: list[str] = field(default_factory=list)
    missing_blocks: list[str] = field(default_factory=list)
    translated_title: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RebuildResult:
    release_id: str
    run_id: str
    status: str
    output_path: Path
    validation_report_path: Path
    chapter_results: list[ChapterRebuildResult]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "run_id": self.run_id,
            "status": self.status,
            "output_path": str(self.output_path),
            "validation_report_path": str(self.validation_report_path),
            "chapter_results": [chapter.to_json_dict() for chapter in self.chapter_results],
        }


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _namespace_uri(tag: str) -> str | None:
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return None


def _qualified_tag(parent: ET.Element, local_name: str) -> str:
    namespace = _namespace_uri(parent.tag)
    return f"{{{namespace}}}{local_name}" if namespace else local_name


def _has_text_content(element: ET.Element) -> bool:
    text_chunks = []
    if element.text:
        text_chunks.append(element.text)
    for child in list(element):
        if child.tail:
            text_chunks.append(child.tail)
    return bool("".join(text_chunks).strip())


def _is_leaf_block(element: ET.Element) -> bool:
    for child in list(element):
        if _local_name(child.tag).lower() in _BLOCK_TAGS:
            return False
    return True


def _text_blocks(root: ET.Element) -> list[ET.Element]:
    return [
        element
        for element in root.iter()
        if _local_name(element.tag).lower() in _BLOCK_TAGS
        and _is_leaf_block(element)
        and (_has_text_content(element) or _local_name(element.tag).lower() == "table")
    ]


def rebuild_epub(unpacked_dir: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    file_paths = sorted(file_path for file_path in unpacked_dir.rglob("*") if file_path.is_file())
    rel_paths = [file_path.relative_to(unpacked_dir).as_posix() for file_path in file_paths]

    with zipfile.ZipFile(output_path, "w") as archive:
        if "mimetype" in rel_paths:
            archive.write(
                unpacked_dir / "mimetype",
                arcname="mimetype",
                compress_type=zipfile.ZIP_STORED,
            )

        for relative_path in rel_paths:
            if relative_path == "mimetype":
                continue
            archive.write(
                unpacked_dir / relative_path,
                arcname=relative_path,
                compress_type=zipfile.ZIP_DEFLATED,
            )

    return output_path


def _translated_text_by_parent(translated_blocks: list[dict[str, Any]]) -> dict[str, str]:
    grouped: dict[str, list[tuple[int, str]]] = {}
    for index, block in enumerate(translated_blocks):
        parent_id = str(block.get("parent_block_id") or block.get("block_id"))
        text = block.get("final_output")
        if text is None:
            text = block.get("restored_text_en")
        if text is None:
            text = block.get("output_text_en")
        segment_order = block.get("segment_order")
        if segment_order is None:
            segment_id = str(block.get("segment_id") or "")
            if "_seg" in segment_id:
                try:
                    segment_order = int(segment_id.rsplit("_seg", 1)[1])
                except ValueError:
                    segment_order = index
            else:
                segment_order = index
        grouped.setdefault(parent_id, []).append((int(segment_order), str(text or "")))
    return {
        parent_id: "".join(text for _, text in sorted(parts, key=lambda item: item[0]))
        for parent_id, parts in grouped.items()
    }


def _placeholder_entries_for_parent(
    placeholder_map: dict[str, Any] | None,
    parent_block_id: str,
) -> list[PlaceholderEntry]:
    if not placeholder_map:
        return []
    blocks = placeholder_map.get("blocks", {})
    if not isinstance(blocks, dict):
        return []
    entries = blocks.get(parent_block_id, [])
    if not isinstance(entries, list):
        return []
    return [PlaceholderEntry(**entry) for entry in entries if isinstance(entry, dict)]


def _restore_translation_fragment(
    *,
    text: str,
    placeholder_map: dict[str, Any] | None,
    parent_block_id: str,
) -> tuple[str, list[str]]:
    entries = _placeholder_entries_for_parent(placeholder_map, parent_block_id)
    if "⟦" not in text or not entries:
        return text, []
    return restore_from_placeholders(text, entries)


def _replace_element_content(element: ET.Element, xhtml_fragment: str) -> None:
    attributes = dict(element.attrib)
    tail = element.tail
    element.clear()
    element.attrib.update(attributes)
    element.tail = tail

    try:
        wrapper = ET.fromstring(f"<wrapper>{xhtml_fragment}</wrapper>")
    except ET.ParseError:
        element.text = xhtml_fragment
        return

    element.text = wrapper.text
    for child in list(wrapper):
        element.append(child)


def _plain_text_from_fragment(xhtml_fragment: str) -> str:
    try:
        wrapper = ET.fromstring(f"<wrapper>{xhtml_fragment}</wrapper>")
    except ET.ParseError:
        text = xhtml_fragment
    else:
        text = "".join(wrapper.itertext())
    return " ".join(text.split())


def _first_element_by_local_name(root: ET.Element, local_name: str) -> ET.Element | None:
    target = local_name.lower()
    return next(
        (element for element in root.iter() if _local_name(element.tag).lower() == target),
        None,
    )


def _direct_child_by_local_name(parent: ET.Element, local_name: str) -> ET.Element | None:
    target = local_name.lower()
    return next(
        (child for child in list(parent) if _local_name(child.tag).lower() == target),
        None,
    )


def _update_xhtml_title(root: ET.Element, translated_title: str) -> None:
    head = _first_element_by_local_name(root, "head")
    if head is None:
        return
    title = _direct_child_by_local_name(head, "title")
    if title is None:
        title = ET.SubElement(head, _qualified_tag(head, "title"))
    for child in list(title):
        title.remove(child)
    title.text = translated_title


def rebuild_chapter_xhtml(
    source_xhtml: str,
    chapter_records: list[dict[str, Any]],
    translated_blocks: list[dict[str, Any]],
    placeholder_map: dict[str, Any] | None = None,
) -> ChapterRebuildResult:
    chapter_number = int(chapter_records[0].get("chapter_number", 0)) if chapter_records else 0
    source_document_path = str(chapter_records[0].get("source_document_path", "")) if chapter_records else ""
    try:
        root = ET.fromstring(source_xhtml.encode("utf-8"))
    except ET.ParseError:
        return ChapterRebuildResult(
            chapter_number=chapter_number,
            source_document_path=source_document_path,
            xhtml=source_xhtml,
            status="failed",
            flags=["xhtml_parse_failed"],
        )

    records_by_parent: dict[str, dict[str, Any]] = {}
    for record in sorted(
        chapter_records,
        key=lambda item: (int(item.get("block_order", 0)), int(item.get("segment_order") or 0)),
    ):
        records_by_parent.setdefault(str(record["parent_block_id"]), record)

    translated_by_parent = _translated_text_by_parent(translated_blocks)
    flags: list[str] = []
    missing_blocks: list[str] = []
    translated_title: str | None = None
    blocks = _text_blocks(root)
    for index, parent_block_id in enumerate(records_by_parent, start=0):
        if index >= len(blocks):
            flags.append("unmapped_block")
            missing_blocks.append(parent_block_id)
            continue
        translated_text = translated_by_parent.get(parent_block_id)
        if translated_text is None or translated_text == "":
            flags.append("missing_translation")
            missing_blocks.append(parent_block_id)
            continue
        element = blocks[index]
        restored_text, restore_warnings = _restore_translation_fragment(
            text=translated_text,
            placeholder_map=placeholder_map,
            parent_block_id=parent_block_id,
        )
        if restore_warnings:
            flags.append("placeholder_restoration_warning")
        if translated_title is None and _local_name(element.tag).lower() in _HEADING_TAGS:
            candidate_title = _plain_text_from_fragment(restored_text)
            if candidate_title:
                translated_title = candidate_title
                _update_xhtml_title(root, translated_title)
        _replace_element_content(element, restored_text)

    xhtml = ET.tostring(root, encoding="unicode")
    try:
        ET.fromstring(xhtml.encode("utf-8"))
    except ET.ParseError:
        flags.append("xhtml_parse_failed")

    return ChapterRebuildResult(
        chapter_number=chapter_number,
        source_document_path=source_document_path,
        xhtml=xhtml,
        status="failed" if flags else "success",
        flags=sorted(set(flags)),
        missing_blocks=missing_blocks,
        translated_title=translated_title,
    )


def _normalize_epub_relative_path(path: str) -> str:
    return posixpath.normpath(path.replace("\\", "/").lstrip("/"))


def _navigation_target_path(
    *,
    work_dir: Path,
    navigation_path: Path,
    href: str,
) -> str | None:
    cleaned = urllib.parse.unquote(href).split("#", 1)[0].split("?", 1)[0].strip()
    if not cleaned:
        return None

    direct = _normalize_epub_relative_path(cleaned)
    if (work_dir / Path(direct)).exists():
        return direct

    try:
        relative = (navigation_path.parent / Path(cleaned)).resolve().relative_to(
            work_dir.resolve()
        )
    except ValueError:
        return None
    return _normalize_epub_relative_path(relative.as_posix())


def _write_xml_tree(tree: Any, path: Path) -> None:
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _sync_ncx_titles(
    ncx_path: Path,
    *,
    work_dir: Path,
    translated_titles_by_source: dict[str, str],
) -> int:
    tree = ET.parse(ncx_path)
    root = tree.getroot()
    updated = 0
    for nav_point in root.iter():
        if _local_name(nav_point.tag) != "navPoint":
            continue
        content = _direct_child_by_local_name(nav_point, "content")
        if content is None:
            continue
        target = _navigation_target_path(
            work_dir=work_dir,
            navigation_path=ncx_path,
            href=content.attrib.get("src", ""),
        )
        if target is None:
            continue
        translated_title = translated_titles_by_source.get(target)
        if not translated_title:
            continue
        nav_label = _direct_child_by_local_name(nav_point, "navLabel")
        text_node = (
            _direct_child_by_local_name(nav_label, "text")
            if nav_label is not None
            else None
        )
        if text_node is not None and text_node.text != translated_title:
            text_node.text = translated_title
            updated += 1

    if updated:
        _write_xml_tree(tree, ncx_path)
    return updated


def _attribute_local_name(attribute_name: str) -> str:
    if "}" in attribute_name:
        return attribute_name.rsplit("}", 1)[1]
    return attribute_name


def _has_epub_type(element: ET.Element, expected: str) -> bool:
    for attribute_name, value in element.attrib.items():
        if _attribute_local_name(attribute_name) == "type" and expected in value.split():
            return True
    return False


def _replace_anchor_text(anchor: ET.Element, translated_title: str) -> None:
    for child in list(anchor):
        anchor.remove(child)
    anchor.text = translated_title


def _sync_nav_xhtml_titles(
    nav_path: Path,
    *,
    work_dir: Path,
    translated_titles_by_source: dict[str, str],
) -> int:
    tree = ET.parse(nav_path)
    root = tree.getroot()
    toc_navs = [
        element
        for element in root.iter()
        if _local_name(element.tag).lower() == "nav" and _has_epub_type(element, "toc")
    ]
    updated = 0
    for toc_nav in toc_navs:
        for anchor in toc_nav.iter():
            if _local_name(anchor.tag).lower() != "a":
                continue
            target = _navigation_target_path(
                work_dir=work_dir,
                navigation_path=nav_path,
                href=anchor.attrib.get("href", ""),
            )
            if target is None:
                continue
            translated_title = translated_titles_by_source.get(target)
            if not translated_title:
                continue
            current_text = " ".join("".join(anchor.itertext()).split())
            if current_text != translated_title:
                _replace_anchor_text(anchor, translated_title)
                updated += 1

    if updated:
        _write_xml_tree(tree, nav_path)
    return updated


def _sync_navigation_titles(
    *,
    work_dir: Path,
    translated_titles_by_source: dict[str, str],
) -> tuple[int, list[str]]:
    if not translated_titles_by_source:
        return (0, [])

    updated = 0
    warnings: list[str] = []
    for ncx_path in work_dir.rglob("toc.ncx"):
        try:
            updated += _sync_ncx_titles(
                ncx_path,
                work_dir=work_dir,
                translated_titles_by_source=translated_titles_by_source,
            )
        except ET.ParseError:
            warnings.append(f"navigation_parse_failed:{ncx_path.relative_to(work_dir).as_posix()}")
        except OSError as exc:
            warnings.append(
                f"navigation_write_failed:{ncx_path.relative_to(work_dir).as_posix()}:{exc}"
            )

    for nav_path in work_dir.rglob("nav.xhtml"):
        try:
            updated += _sync_nav_xhtml_titles(
                nav_path,
                work_dir=work_dir,
                translated_titles_by_source=translated_titles_by_source,
            )
        except ET.ParseError:
            warnings.append(f"navigation_parse_failed:{nav_path.relative_to(work_dir).as_posix()}")
        except OSError as exc:
            warnings.append(
                f"navigation_write_failed:{nav_path.relative_to(work_dir).as_posix()}:{exc}"
            )

    return (updated, warnings)


def _load_final_blocks(translation_dir: Path) -> list[dict[str, Any]]:
    pass3_path = translation_dir / "pass3.json"
    if pass3_path.exists():
        payload = _read_json(pass3_path)
        blocks = [block for block in payload.get("blocks", []) if block.get("final_output") is not None]
        if blocks:
            return blocks

    pass2_path = translation_dir / "pass2.json"
    if pass2_path.exists():
        return list(_read_json(pass2_path).get("blocks", []))
    return []


def _resolve_source_relative_path(unpacked_dir: Path, source_document_path: str) -> Path:
    direct = Path(source_document_path)
    if (unpacked_dir / direct).exists():
        return direct

    source_posix = direct.as_posix().lstrip("/")
    matches = [
        path.relative_to(unpacked_dir)
        for path in unpacked_dir.rglob(direct.name)
        if path.is_file() and path.relative_to(unpacked_dir).as_posix().endswith(source_posix)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous source document path: {source_document_path}")
    return direct


def validate_reconstruction(
    *,
    release_id: str,
    run_id: str,
    chapter_results: list[ChapterRebuildResult],
    output_path: Path,
) -> ValidationReport:
    flags = sorted({flag for chapter in chapter_results for flag in chapter.flags})
    if not output_path.exists():
        flags.append("packaging_failed")
    return ValidationReport(
        report_id=f"recon-{release_id}-{run_id}",
        report_scope="run",
        release_id=release_id,
        run_id=run_id,
        chapter_number=None,
        status="failed" if flags else "success",
        severity="error" if flags else "info",
        flags=flags,
        artifact_refs=[str(output_path)] if output_path.exists() else [],
    )


def rebuild_translated_epub(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig | None = None,
    output_path: Path | None = None,
    project_root: Path | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
) -> RebuildResult:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    chapter_refs = list_extracted_chapters(paths, chapter_start=chapter_start, chapter_end=chapter_end)
    reconstruction_root = paths.release_root / "runs" / run_id / "reconstruction"
    chapters_out = reconstruction_root / "chapters"
    work_dir = reconstruction_root / "work"
    final_output = output_path or reconstruction_root / "reconstructed.epub"
    validation_report_path = reconstruction_root / "validation-report.json"

    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.started",
        total_chapters=len(chapter_refs),
        message=f"EPUB rebuild started for {len(chapter_refs)} chapters",
    )

    chapter_results: list[ChapterRebuildResult] = []
    translated_titles_by_source: dict[str, str] = {}
    try:
        if work_dir.exists():
            shutil.rmtree(work_dir)
        shutil.copytree(paths.unpacked_dir, work_dir)
        chapters_out.mkdir(parents=True, exist_ok=True)

        conn = open_connection(paths.db_path)
        ensure_schema(conn, "summaries")
        try:
            non_story_chapters = {
                ref.chapter_number
                for ref in chapter_refs
                if is_non_story_chapter(conn, release_id=release_id, chapter_number=ref.chapter_number)
            }
        finally:
            conn.close()

        for chapter_ref in chapter_refs:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.chapter_started",
                chapter_number=chapter_ref.chapter_number,
                message=f"EPUB rebuild started for chapter {chapter_ref.chapter_number}",
            )
            try:
                translation_dir = (
                    paths.release_root
                    / "runs"
                    / run_id
                    / "translation"
                    / f"chapter-{chapter_ref.chapter_number}"
                )
                translated_blocks = _load_final_blocks(translation_dir)
                if chapter_ref.chapter_number in non_story_chapters and not translated_blocks:
                    result = ChapterRebuildResult(
                        chapter_number=chapter_ref.chapter_number,
                        source_document_path=chapter_ref.source_document_path or "",
                        xhtml="",
                        status="skipped",
                        flags=[],
                    )
                    chapter_results.append(result)
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.chapter_skipped",
                        chapter_number=chapter_ref.chapter_number,
                        severity="warning",
                        message=f"EPUB rebuild skipped chapter {chapter_ref.chapter_number}: non-story chapter",
                        reason="non_story_chapter",
                    )
                    continue
                chapter_path = chapter_ref.chapter_path
                chapter_payload = _read_json(chapter_path)
                chapter_number = int(chapter_payload["chapter_number"])
                source_document_path = str(chapter_payload["source_document_path"])
                source_relative_path = _resolve_source_relative_path(paths.unpacked_dir, source_document_path)
                source_path = paths.unpacked_dir / source_relative_path
                work_source_path = work_dir / source_relative_path
                placeholder_path = paths.extracted_placeholders_dir / f"chapter-{chapter_number}.json"
                placeholder_map = _read_json(placeholder_path) if placeholder_path.exists() else {}
                if not translated_blocks:
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.translation_missing",
                        chapter_number=chapter_number,
                        severity="warning",
                        message=f"EPUB rebuild found no translated blocks for chapter {chapter_number}",
                        reason="missing_translated_blocks",
                    )
                result = rebuild_chapter_xhtml(
                    source_xhtml=source_path.read_text(encoding="utf-8"),
                    chapter_records=list(chapter_payload.get("records", [])),
                    translated_blocks=translated_blocks,
                    placeholder_map=placeholder_map,
                )
                chapter_results.append(result)
                for flag in result.flags:
                    severity = "error" if flag in {"xhtml_parse_failed"} else "warning"
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.chapter_warning",
                        chapter_number=chapter_number,
                        severity=severity,
                        message=f"EPUB rebuild warning for chapter {chapter_number}: {flag}",
                        reason=flag,
                        missing_blocks=result.missing_blocks,
                    )
                if result.status == "success":
                    if result.translated_title:
                        translated_titles_by_source[
                            _normalize_epub_relative_path(source_relative_path.as_posix())
                        ] = result.translated_title
                    chapter_artifact = chapters_out / f"chapter-{chapter_number}.xhtml"
                    chapter_artifact.write_text(
                        result.xhtml,
                        encoding="utf-8",
                    )
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.artifact_written",
                        chapter_number=chapter_number,
                        message=f"Rebuilt chapter artifact written for chapter {chapter_number}",
                        artifact_path=str(chapter_artifact),
                    )
                    work_source_path.parent.mkdir(parents=True, exist_ok=True)
                    work_source_path.write_text(result.xhtml, encoding="utf-8")
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.chapter_completed",
                        chapter_number=chapter_number,
                        message=f"EPUB rebuild completed for chapter {chapter_number}",
                    )
                else:
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.chapter_failed",
                        chapter_number=chapter_number,
                        severity="error",
                        message=f"EPUB rebuild failed for chapter {chapter_number}",
                        reason=";".join(result.flags) or "chapter_rebuild_failed",
                        missing_blocks=result.missing_blocks,
                    )
            except Exception as exc:
                logger.opt(exception=True).error(
                    "EPUB rebuild failed for chapter {}",
                    chapter_ref.chapter_number,
                )
                result = ChapterRebuildResult(
                    chapter_number=chapter_ref.chapter_number,
                    source_document_path=chapter_ref.source_document_path or "",
                    xhtml="",
                    status="failed",
                    flags=["chapter_rebuild_exception"],
                )
                chapter_results.append(result)
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.chapter_failed",
                    chapter_number=chapter_ref.chapter_number,
                    severity="error",
                    message=f"EPUB rebuild failed for chapter {chapter_ref.chapter_number}: {exc}",
                    reason=str(exc),
                )

        updated_navigation_entries, navigation_warnings = _sync_navigation_titles(
            work_dir=work_dir,
            translated_titles_by_source=translated_titles_by_source,
        )
        if updated_navigation_entries:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.navigation_updated",
                message=f"EPUB rebuild updated {updated_navigation_entries} navigation entries",
                updated_count=updated_navigation_entries,
            )
        for warning in navigation_warnings:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.navigation_warning",
                severity="warning",
                message=f"EPUB rebuild navigation warning: {warning}",
                reason=warning,
            )

        try:
            rebuilt_path = rebuild_epub(work_dir, final_output)
        except Exception as exc:
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.failed",
                severity="error",
                message=f"EPUB rebuild packaging failed: {exc}",
                reason=str(exc),
            )
            raise
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.artifact_written",
            message="Rebuilt EPUB artifact written",
            artifact_path=str(rebuilt_path),
        )
        report = validate_reconstruction(
            release_id=release_id,
            run_id=run_id,
            chapter_results=chapter_results,
            output_path=rebuilt_path,
        )
        _write_json(validation_report_path, report.to_json_dict())
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.validation_completed",
            severity="error" if report.status == "failed" else "info",
            message=f"EPUB rebuild validation {report.status}",
            status=report.status,
            flags=report.flags,
            artifact_path=str(validation_report_path),
        )
        _write_json(
            reconstruction_root / "manifest.json",
            {
                "release_id": release_id,
                "run_id": run_id,
                "schema_version": "1.0",
                "output_path": str(rebuilt_path),
                "validation_report_path": str(validation_report_path),
                "chapters": [chapter.to_json_dict() for chapter in chapter_results],
            },
        )
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.completed",
            severity="error" if report.status == "failed" else "info",
            message=f"EPUB rebuild completed with status {report.status}",
            status=report.status,
            failed_count=sum(1 for chapter in chapter_results if chapter.status == "failed"),
            skipped_count=sum(1 for chapter in chapter_results if chapter.status == "skipped"),
            artifact_path=str(rebuilt_path),
        )
        return RebuildResult(
            release_id=release_id,
            run_id=run_id,
            status=report.status,
            output_path=rebuilt_path,
            validation_report_path=validation_report_path,
            chapter_results=chapter_results,
        )
    except Exception as exc:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.failed",
            severity="error",
            message=f"EPUB rebuild failed: {exc}",
            reason=str(exc),
        )
        raise
