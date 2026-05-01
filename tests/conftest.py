from __future__ import annotations

import uuid
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from resemantica.settings import AppConfig, TranslationConfig


def _write_extracted_chapter(
    tmp_path: Path,
    *,
    release_id: str,
    chapter_number: int = 1,
    source_text: str = "test",
    chapter_source_hash: str | None = None,
) -> None:
    from resemantica.settings import derive_paths, load_config

    config = load_config()
    paths = derive_paths(config, release_id=release_id, project_root=tmp_path)
    chapter_dir = paths.extracted_chapters_dir
    chapter_dir.mkdir(parents=True, exist_ok=True)
    source_hash = chapter_source_hash or sha256(source_text.encode("utf-8")).hexdigest()[:16]
    payload = {
        "chapter_number": chapter_number,
        "source_document_path": f"chapter-{chapter_number}.xhtml",
        "chapter_source_hash": source_hash,
        "records": [
            {
                "block_id": f"ch{chapter_number:03d}_blk001",
                "chapter_id": f"ch{chapter_number:03d}",
                "chapter_number": chapter_number,
                "segment_id": None,
                "parent_block_id": f"ch{chapter_number:03d}_blk001",
                "block_order": 1,
                "segment_order": None,
                "source_text_zh": source_text,
                "placeholder_map_ref": "none",
                "chapter_source_hash": source_hash,
                "schema_version": 1,
            }
        ],
    }
    path = chapter_dir / f"chapter-{chapter_number}.json"
    path.write_text(
        __import__("json").dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _make_event(*, event_type: str = "test.event", severity: str = "info") -> object:
    from resemantica.tracking.models import Event

    return Event(
        event_id=str(uuid.uuid4().hex[:16]),
        run_id="test-run",
        release_id="test-release",
        event_type=event_type,
        stage_name="test",
        severity=severity,
        message="",
        chapter_number=None,
        block_id=None,
        payload={},
        created_at=datetime.now(UTC).isoformat(),
    )


def _make_config(*, pass3_default: bool = False) -> AppConfig:
    return AppConfig(translation=TranslationConfig(pass3_default=pass3_default))
