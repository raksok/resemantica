from __future__ import annotations

import json
from pathlib import Path

from resemantica.db.packet_repo import ensure_packet_schema, save_packet_metadata
from resemantica.db.sqlite import open_connection
from resemantica.packets.models import PacketMetadataRecord
from resemantica.settings import derive_paths, load_config
from resemantica.tracking.repo import ensure_tracking_db, load_events
from resemantica.translation.bundle_context import load_bundles_for_chapter
from resemantica.translation.pipeline import _emit_bundle_context_missing_event


def _metadata(*, release_id: str, chapter_number: int, bundle_path: Path) -> PacketMetadataRecord:
    return PacketMetadataRecord(
        packet_id=f"pkt-{chapter_number}",
        release_id=release_id,
        chapter_number=chapter_number,
        run_id="packets",
        packet_path=str(bundle_path.with_suffix(".packet.json")),
        bundle_path=str(bundle_path),
        packet_hash=f"packet-hash-{chapter_number}",
        chapter_source_hash=f"chapter-hash-{chapter_number}",
        glossary_version_hash="glossary-hash",
        summary_version_hash="summary-hash",
        graph_snapshot_hash="graph-hash",
        idiom_policy_hash="idiom-hash",
        packet_builder_version="test",
    )


def _save_metadata(*, release_id: str, chapter_number: int, bundle_path: Path) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    try:
        ensure_packet_schema(conn)
        save_packet_metadata(
            conn,
            metadata=_metadata(
                release_id=release_id,
                chapter_number=chapter_number,
                bundle_path=bundle_path,
            ),
        )
    finally:
        conn.close()


def _load_with_event_callback(*, release_id: str, chapter_number: int) -> None:
    load_bundles_for_chapter(
        release_id=release_id,
        chapter_number=chapter_number,
        warning_callback=lambda payload: _emit_bundle_context_missing_event(
            release_id=release_id,
            run_id="translate",
            chapter_number=chapter_number,
            pass_name="pass1",
            payload=payload,
        ),
    )


def _bundle_missing_events(*, release_id: str):
    conn = ensure_tracking_db(release_id)
    try:
        return [
            event
            for event in load_events(conn, run_id="translate", release_id=release_id, limit=100)
            if event.event_type == "translate-chapter.bundle_context_missing"
        ]
    finally:
        conn.close()


def test_missing_packet_metadata_emits_bundle_context_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "missing-packet-metadata"
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    try:
        ensure_packet_schema(conn)
    finally:
        conn.close()

    _load_with_event_callback(release_id=release_id, chapter_number=1)

    events = _bundle_missing_events(release_id=release_id)
    assert len(events) == 1
    assert events[0].severity == "warning"
    assert events[0].payload["reason"] == "missing_packet_metadata"


def test_missing_bundle_file_emits_bundle_context_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "missing-bundle-file"
    missing_path = tmp_path / "does-not-exist.bundle.json"
    _save_metadata(release_id=release_id, chapter_number=1, bundle_path=missing_path)

    _load_with_event_callback(release_id=release_id, chapter_number=1)

    events = _bundle_missing_events(release_id=release_id)
    assert len(events) == 1
    assert events[0].payload["reason"] == "missing_bundle_file"
    assert events[0].payload["bundle_path"] == str(missing_path)


def test_empty_bundle_rows_emit_bundle_context_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "empty-bundle-rows"
    bundle_path = tmp_path / "empty.bundle.json"
    bundle_path.write_text(json.dumps({"bundles": []}), encoding="utf-8")
    _save_metadata(release_id=release_id, chapter_number=1, bundle_path=bundle_path)

    _load_with_event_callback(release_id=release_id, chapter_number=1)

    events = _bundle_missing_events(release_id=release_id)
    assert len(events) == 1
    assert events[0].payload["reason"] == "empty_bundle_rows"
    assert events[0].payload["pass_name"] == "pass1"
