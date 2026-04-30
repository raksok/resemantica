from __future__ import annotations

import json
from pathlib import Path

from resemantica.packets.builder import build_packets
from resemantica.packets.models import PacketBuildOutput
from resemantica.settings import derive_paths, load_config


def _write_extracted_chapter(*, release_id: str, chapter_number: int) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
    (paths.extracted_chapters_dir / f"chapter-{chapter_number}.json").write_text(
        json.dumps({"chapter_number": chapter_number, "records": [{"source_text_zh": "正文"}]}),
        encoding="utf-8",
    )


def test_build_packets_emits_chapter_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m19-packet-events"
    _write_extracted_chapter(release_id=release_id, chapter_number=1)
    import resemantica.packets.builder as builder_module
    from resemantica.orchestration.events import subscribe, unsubscribe

    def fake_build_chapter_packet(**kwargs):
        chapter_number = kwargs["chapter_number"]
        return PacketBuildOutput(
            status="built",
            release_id=release_id,
            run_id="packet-events",
            chapter_number=chapter_number,
            packet_id="pkt",
            packet_hash="hash",
            packet_path="packet.json",
            bundle_path="bundle.json",
            stale_reasons=[],
        )

    monkeypatch.setattr(builder_module, "build_chapter_packet", fake_build_chapter_packet)
    received = []

    def callback(event):
        if event.run_id == "packet-events":
            received.append(event)

    subscribe("*", callback)
    try:
        build_packets(release_id=release_id, run_id="packet-events")
    finally:
        unsubscribe("*", callback)

    assert [event.event_type for event in received] == [
        "packets-build.started",
        "packets-build.chapter_started",
        "packets-build.chapter_completed",
        "packets-build.completed",
    ]
    assert received[0].payload["total_chapters"] == 1
    assert received[-1].payload["built"] == 1
