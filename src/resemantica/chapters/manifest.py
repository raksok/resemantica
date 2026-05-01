from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from resemantica.settings import DerivedPaths
from resemantica.utils import _chapter_number_from_path

_CHAPTER_FILE_RE = re.compile(r"chapter-(\d+)\.json$")


@dataclass(slots=True)
class ChapterRef:
    chapter_number: int
    chapter_path: Path
    placeholder_path: Path
    source_document_path: str | None
    chapter_source_hash: str | None


def _read_chapter_ref(paths: DerivedPaths, chapter_path: Path) -> ChapterRef:
    try:
        payload = json.loads(chapter_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    chapter_number = int(payload.get("chapter_number") or _chapter_number_from_path(chapter_path))
    source_document_path = payload.get("source_document_path")
    chapter_source_hash = payload.get("chapter_source_hash")
    return ChapterRef(
        chapter_number=chapter_number,
        chapter_path=chapter_path,
        placeholder_path=paths.extracted_placeholders_dir / f"chapter-{chapter_number}.json",
        source_document_path=source_document_path if isinstance(source_document_path, str) else None,
        chapter_source_hash=chapter_source_hash if isinstance(chapter_source_hash, str) else None,
    )


def _scan_chapters(paths: DerivedPaths) -> list[ChapterRef]:
    return sorted(
        [
            _read_chapter_ref(paths, chapter_path)
            for chapter_path in paths.extracted_chapters_dir.glob("chapter-*.json")
        ],
        key=lambda ref: ref.chapter_number,
    )


def _manifest_row(ref: ChapterRef) -> dict[str, Any]:
    return {
        **asdict(ref),
        "chapter_path": str(ref.chapter_path),
        "placeholder_path": str(ref.placeholder_path),
    }


def write_chapter_manifest(paths: DerivedPaths) -> Path:
    refs = _scan_chapters(paths)
    payload = {
        "schema_version": 1,
        "chapters": [_manifest_row(ref) for ref in refs],
    }
    paths.extracted_chapter_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.extracted_chapter_manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return paths.extracted_chapter_manifest_path


def _load_manifest(paths: DerivedPaths) -> list[ChapterRef]:
    payload = json.loads(paths.extracted_chapter_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("chapter manifest root must be an object")
    rows = payload.get("chapters")
    if not isinstance(rows, list):
        raise ValueError("chapter manifest chapters must be a list")

    refs: list[ChapterRef] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("chapter manifest row must be an object")
        refs.append(
            ChapterRef(
                chapter_number=int(row["chapter_number"]),
                chapter_path=Path(str(row["chapter_path"])),
                placeholder_path=Path(str(row["placeholder_path"])),
                source_document_path=(
                    str(row["source_document_path"])
                    if row.get("source_document_path") is not None
                    else None
                ),
                chapter_source_hash=(
                    str(row["chapter_source_hash"])
                    if row.get("chapter_source_hash") is not None
                    else None
                ),
            )
        )
    return sorted(refs, key=lambda ref: ref.chapter_number)


def list_extracted_chapters(
    paths: DerivedPaths,
    *,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
) -> list[ChapterRef]:
    try:
        refs = _load_manifest(paths)
    except (FileNotFoundError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        write_chapter_manifest(paths)
        refs = _load_manifest(paths)

    return [
        ref
        for ref in refs
        if (chapter_start is None or ref.chapter_number >= chapter_start)
        and (chapter_end is None or ref.chapter_number <= chapter_end)
    ]
