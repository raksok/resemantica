from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any
from xml.etree import ElementTree as ET
import zipfile

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.epub.models import PlaceholderEntry
from resemantica.epub.placeholders import restore_from_placeholders
from resemantica.settings import AppConfig, derive_paths, load_config

_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "li", "td", "table"}


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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


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
    )


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
) -> RebuildResult:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    reconstruction_root = paths.release_root / "runs" / run_id / "reconstruction"
    chapters_out = reconstruction_root / "chapters"
    work_dir = reconstruction_root / "work"
    final_output = output_path or reconstruction_root / "reconstructed.epub"
    validation_report_path = reconstruction_root / "validation-report.json"

    if work_dir.exists():
        shutil.rmtree(work_dir)
    shutil.copytree(paths.unpacked_dir, work_dir)
    chapters_out.mkdir(parents=True, exist_ok=True)

    chapter_results: list[ChapterRebuildResult] = []
    for chapter_ref in list_extracted_chapters(paths):
        chapter_path = chapter_ref.chapter_path
        chapter_payload = _read_json(chapter_path)
        chapter_number = int(chapter_payload["chapter_number"])
        source_document_path = str(chapter_payload["source_document_path"])
        source_path = paths.unpacked_dir / source_document_path
        work_source_path = work_dir / source_document_path
        translation_dir = paths.release_root / "runs" / run_id / "translation" / f"chapter-{chapter_number}"
        placeholder_path = paths.extracted_placeholders_dir / f"chapter-{chapter_number}.json"
        placeholder_map = _read_json(placeholder_path) if placeholder_path.exists() else {}
        result = rebuild_chapter_xhtml(
            source_xhtml=source_path.read_text(encoding="utf-8"),
            chapter_records=list(chapter_payload.get("records", [])),
            translated_blocks=_load_final_blocks(translation_dir),
            placeholder_map=placeholder_map,
        )
        chapter_results.append(result)
        if result.status == "success":
            chapters_out.joinpath(f"chapter-{chapter_number}.xhtml").write_text(
                result.xhtml,
                encoding="utf-8",
            )
            work_source_path.parent.mkdir(parents=True, exist_ok=True)
            work_source_path.write_text(result.xhtml, encoding="utf-8")

    rebuilt_path = rebuild_epub(work_dir, final_output)
    report = validate_reconstruction(
        release_id=release_id,
        run_id=run_id,
        chapter_results=chapter_results,
        output_path=rebuilt_path,
    )
    _write_json(validation_report_path, report.to_json_dict())
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
    return RebuildResult(
        release_id=release_id,
        run_id=run_id,
        status=report.status,
        output_path=rebuilt_path,
        validation_report_path=validation_report_path,
        chapter_results=chapter_results,
    )
