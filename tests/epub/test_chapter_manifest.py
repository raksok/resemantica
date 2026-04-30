from __future__ import annotations

import json
from pathlib import Path

from resemantica.chapters.manifest import list_extracted_chapters, write_chapter_manifest
from resemantica.settings import derive_paths, load_config


def _write_chapter(paths, number: int, source_hash: str) -> None:
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "chapter_number": number,
        "source_document_path": f"OEBPS/chapter{number}.xhtml",
        "chapter_source_hash": source_hash,
        "records": [],
    }
    (paths.extracted_chapters_dir / f"chapter-{number}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_manifest_write_and_range_listing_preserves_numeric_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    paths = derive_paths(load_config(), release_id="manifest")
    _write_chapter(paths, 10, "hash-10")
    _write_chapter(paths, 2, "hash-2")
    _write_chapter(paths, 1, "hash-1")

    manifest_path = write_chapter_manifest(paths)
    refs = list_extracted_chapters(paths, chapter_start=2, chapter_end=10)

    assert manifest_path == paths.extracted_chapter_manifest_path
    assert manifest_path.exists()
    assert [ref.chapter_number for ref in refs] == [2, 10]
    assert refs[0].chapter_source_hash == "hash-2"
    assert refs[0].placeholder_path == paths.extracted_placeholders_dir / "chapter-2.json"


def test_manifest_missing_falls_back_to_scan_and_rewrites(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    paths = derive_paths(load_config(), release_id="manifest-fallback")
    _write_chapter(paths, 3, "hash-3")

    refs = list_extracted_chapters(paths)

    assert [ref.chapter_number for ref in refs] == [3]
    assert paths.extracted_chapter_manifest_path.exists()
