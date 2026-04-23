from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ChapterDocument:
    chapter_number: int
    manifest_id: str
    href: str
    absolute_path: Path


@dataclass(slots=True)
class PlaceholderEntry:
    placeholder: str
    element: str
    attributes: dict[str, str]
    original_xhtml: str
    parent_placeholder: str | None
    depth: int
    closing_order: list[str] | None = None
    emitted: bool = True

    def to_json_dict(self) -> dict[str, object]:
        data = asdict(self)
        data.pop("emitted", None)
        return data


@dataclass(slots=True)
class ExtractedRecord:
    chapter_id: str
    chapter_number: int
    source_document_path: str
    block_id: str
    parent_block_id: str
    segment_id: str | None
    block_order: int
    segment_order: int | None
    source_text_zh: str
    placeholder_map_ref: str
    chapter_source_hash: str
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ChapterParseResult:
    chapter_number: int
    chapter_id: str
    source_document_path: str
    chapter_source_hash: str
    records: list[ExtractedRecord] = field(default_factory=list)
    placeholders_by_block: dict[str, list[PlaceholderEntry]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass(slots=True)
class RoundTripResult:
    release_id: str
    release_root: Path
    rebuilt_epub_path: Path
    validation_report_path: Path
    chapter_results: list[ChapterParseResult]

    @property
    def status(self) -> str:
        if any(not chapter.is_valid for chapter in self.chapter_results):
            return "failed"
        return "success"

