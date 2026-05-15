from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from resemantica.chapters.manifest import write_chapter_manifest
from resemantica.db.glossary_repo import ensure_glossary_schema, upsert_discovered_candidates, upsert_translation_vote
from resemantica.db.graph_repo import ensure_graph_schema, save_graph_snapshot
from resemantica.db.idiom_repo import ensure_idiom_schema
from resemantica.db.idiom_repo import upsert_discovered_candidates as upsert_idiom_candidates
from resemantica.db.idiom_repo import upsert_translation_vote as upsert_idiom_vote
from resemantica.db.packet_repo import ensure_packet_schema, save_packet_metadata
from resemantica.db.sqlite import open_connection
from resemantica.db.summary_repo import (
    ensure_summary_schema,
    save_chapter_structured_and_short,
    save_summary_draft,
    save_validated_summary,
)
from resemantica.glossary.models import GlossaryCandidate
from resemantica.graph.models import GraphSnapshotRecord
from resemantica.idioms.models import IdiomCandidate
from resemantica.orchestration.gates import check_stage_gate
from resemantica.orchestration.runner import OrchestrationRunner
from resemantica.packets.models import PacketMetadataRecord
from resemantica.settings import derive_paths, load_config
from resemantica.tracking.repo import ensure_tracking_db, load_events, load_run_state


def _write_extracted_chapter(release_id: str, chapter_number: int = 1) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
    block_id = f"ch{chapter_number:03d}_blk001"
    payload = {
        "chapter_id": f"chapter-{chapter_number}",
        "chapter_number": chapter_number,
        "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
        "chapter_source_hash": f"hash-{chapter_number}",
        "records": [
            {
                "chapter_id": f"chapter-{chapter_number}",
                "chapter_number": chapter_number,
                "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
                "block_id": block_id,
                "parent_block_id": block_id,
                "segment_id": None,
                "block_order": 1,
                "segment_order": None,
                "source_text_zh": "第一段。",
                "placeholder_map_ref": str(paths.extracted_placeholders_dir / f"chapter-{chapter_number}.json"),
                "chapter_source_hash": f"hash-{chapter_number}",
                "schema_version": 1,
            }
        ],
    }
    (paths.extracted_chapters_dir / f"chapter-{chapter_number}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    paths.extracted_placeholders_dir.mkdir(parents=True, exist_ok=True)
    (paths.extracted_placeholders_dir / f"chapter-{chapter_number}.json").write_text(
        json.dumps({"blocks": {}}),
        encoding="utf-8",
    )
    write_chapter_manifest(paths)


def _seed_summary(release_id: str, chapter_number: int = 1, *, is_story: bool = True) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        save_summary_draft(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_structured",
            content={"is_story_chapter": is_story, "events": []},
            chapter_source_hash=f"hash-{chapter_number}",
            model_name="analyst",
            prompt_version="v1",
            run_id="summaries",
            validation_status="approved" if is_story else "non_story_chapter",
            is_story_chapter=1 if is_story else 0,
        )
        save_chapter_structured_and_short(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            structured_summary={"is_story_chapter": is_story, "events": []},
            narrative_progression="故事继续。",
            derived_from_chapter_hash=f"hash-{chapter_number}",
            run_id="summaries",
            validation_status="approved" if is_story else "non_story_chapter",
        )
        if is_story:
            save_validated_summary(
                conn,
                release_id=release_id,
                chapter_number=chapter_number,
                summary_type="story_so_far_zh",
                content_zh="故事继续。",
                derived_from_chapter_hash=f"hash-{chapter_number}",
                run_id="summaries",
                validation_status="approved",
            )
        else:
            conn.execute(
                """
                UPDATE summary_drafts
                SET is_story_chapter = 0, validation_status = 'non_story_chapter'
                WHERE release_id = ? AND chapter_number = ?
                """,
                (release_id, chapter_number),
            )
    finally:
        conn.close()
    paths.summaries_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("zh", "en"):
        (paths.summaries_dir / f"chapter-{chapter_number}-{suffix}.json").write_text(
            json.dumps({"chapter_number": chapter_number}),
            encoding="utf-8",
        )


def _seed_graph(release_id: str) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    snapshot = GraphSnapshotRecord(
        snapshot_id="snap-1",
        release_id=release_id,
        snapshot_hash="a" * 64,
        graph_db_path=str(paths.graph_db_path),
        entity_count=0,
        alias_count=0,
        appearance_count=0,
        relationship_count=0,
        created_at=datetime.now(UTC).isoformat(),
    )
    conn = open_connection(paths.db_path)
    ensure_graph_schema(conn)
    try:
        save_graph_snapshot(conn, snapshot=snapshot)
    finally:
        conn.close()
    paths.graph_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    paths.graph_snapshot_path.write_text(json.dumps({"snapshot": snapshot.to_json_dict()}), encoding="utf-8")


def _seed_packet(release_id: str, run_id: str, chapter_number: int = 1) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    paths.packets_dir.mkdir(parents=True, exist_ok=True)
    packet_path = paths.packets_dir / f"chapter-{chapter_number}-pkt.json"
    bundle_path = paths.packets_dir / f"chapter-{chapter_number}-bundles.json"
    packet_path.write_text(json.dumps({"chapter_number": chapter_number}), encoding="utf-8")
    bundle_path.write_text(json.dumps({"bundles": []}), encoding="utf-8")
    conn = open_connection(paths.db_path)
    ensure_packet_schema(conn)
    try:
        save_packet_metadata(
            conn,
            metadata=PacketMetadataRecord(
                packet_id=f"pkt-{chapter_number}",
                release_id=release_id,
                chapter_number=chapter_number,
                run_id=run_id,
                packet_path=str(packet_path),
                bundle_path=str(bundle_path),
                packet_hash="p" * 64,
                chapter_source_hash=f"hash-{chapter_number}",
                glossary_version_hash="g" * 64,
                summary_version_hash="s" * 64,
                graph_snapshot_hash="a" * 64,
                idiom_policy_hash="i" * 64,
                packet_builder_version="test",
            ),
        )
    finally:
        conn.close()


def _seed_translation(release_id: str, run_id: str, chapter_number: int = 1) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    translation_dir = paths.release_root / "runs" / run_id / "translation" / f"chapter-{chapter_number}"
    translation_dir.mkdir(parents=True, exist_ok=True)
    (translation_dir / "pass2.json").write_text(
        json.dumps({"blocks": [{"block_id": "ch001_blk001", "output_text_en": "Translated."}]}),
        encoding="utf-8",
    )


def _seed_story_inputs(release_id: str, run_id: str) -> None:
    _write_extracted_chapter(release_id)
    _seed_summary(release_id)
    _seed_graph(release_id)
    _seed_packet(release_id, run_id)
    _seed_translation(release_id, run_id)


def _seed_unresolved_idiom_vote(release_id: str) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        upsert_idiom_candidates(
            conn,
            candidates=[
                IdiomCandidate(
                    candidate_id="ican-unresolved",
                    release_id=release_id,
                    source_text="一箭双雕",
                    normalized_source_text="一箭双雕",
                    meaning_zh="一举两得",
                    preferred_rendering_en="",
                    usage_notes=None,
                    first_seen_chapter=1,
                    last_seen_chapter=1,
                    appearance_count=1,
                    evidence_snippet="一箭双雕",
                    detection_run_id="idioms",
                    candidate_status="discovered",
                    validation_status="pending",
                    conflict_reason=None,
                    analyst_model_name="analyst",
                    analyst_prompt_version="v1",
                )
            ],
        )
        upsert_idiom_vote(
            conn,
            candidate_id="ican-unresolved",
            release_id=release_id,
            translation_run_id="idioms",
            model_name="m1",
            prompt_version="v1",
            vote_kind="rendering",
            raw_output="A",
            cleaned_output="A",
            normalized_output="a",
            resolution_status="unresolved",
        )
    finally:
        conn.close()


def test_missing_extracted_manifest_blocks_preprocess(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    report = check_stage_gate(
        stage_name="preprocess-summaries",
        release_id="missing-extract",
        run_id="run",
        config=load_config(),
    )

    assert report.success is False
    assert "Missing extracted chapter manifest" in report.message()


def test_dry_run_includes_gate_preview(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = OrchestrationRunner("dry-gates", "production").run_production(dry_run=True)

    assert result.success is True
    first_stage = result.metadata["stages"][0]
    assert first_stage["stage_name"] == "preprocess-summaries"
    assert first_stage["gate"]["success"] is False


def test_production_gate_failure_persists_event_before_execution(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []

    def fake_execute_stage(self, stage_name, **kwargs):
        calls.append(stage_name)
        raise AssertionError("stage should not execute")

    monkeypatch.setattr(OrchestrationRunner, "_execute_stage", fake_execute_stage)

    result = OrchestrationRunner("prod-gates", "production").run_production()

    assert result.success is False
    assert calls == []
    conn = ensure_tracking_db("prod-gates")
    try:
        events = load_events(conn, run_id="production", release_id="prod-gates")
        state = load_run_state(conn, "production")
    finally:
        conn.close()
    assert any(event.event_type == "preprocess-summaries.gate_failed" for event in events)
    assert state is not None
    assert state.stage_name == "preprocess-summaries"
    assert state.status == "failed"


def test_production_retries_failed_gate_stage_after_gate_cleared(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "prod-gate-resume"
    run_id = "production"
    _write_extracted_chapter(release_id)
    _seed_summary(release_id)
    executed: list[str] = []

    def fake_execute_stage(self, stage_name, **kwargs):
        executed.append(stage_name)
        if stage_name == "preprocess-idioms":
            _seed_unresolved_idiom_vote(release_id)
        from resemantica.orchestration.models import StageResult

        return StageResult(True, stage_name, "ok")

    monkeypatch.setattr(OrchestrationRunner, "_execute_stage", fake_execute_stage)

    first = OrchestrationRunner(release_id, run_id).run_production(chapter_start=1, chapter_end=1)

    assert first.success is False
    assert executed == ["preprocess-summaries", "preprocess-glossary", "preprocess-idioms"]
    conn = ensure_tracking_db(release_id)
    try:
        state = load_run_state(conn, run_id)
    finally:
        conn.close()
    assert state is not None
    assert state.stage_name == "preprocess-graph"
    assert state.status == "failed"
    assert state.checkpoint["chapter_start"] == 1
    assert state.checkpoint["chapter_end"] == 1

    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    try:
        conn.execute(
            """
            UPDATE idiom_candidates
            SET preferred_rendering_en = 'two birds with one stone'
            WHERE candidate_id = ?
            """,
            ("ican-unresolved",),
        )
        conn.execute(
            """
            UPDATE idiom_translation_votes
            SET resolution_status = 'resolved'
            WHERE candidate_id = ?
            """,
            ("ican-unresolved",),
        )
        conn.commit()
    finally:
        conn.close()

    executed.clear()
    second = OrchestrationRunner(release_id, run_id).run_production()

    assert executed[0] == "preprocess-graph"
    assert second.success is False
    assert "preprocess-summaries" not in executed


def test_unresolved_glossary_and_idiom_votes_block_downstream(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "vote-gate"
    _write_extracted_chapter(release_id)
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    ensure_idiom_schema(conn)
    try:
        upsert_discovered_candidates(
            conn,
            candidates=[
                GlossaryCandidate(
                    candidate_id="gcan-1",
                    release_id=release_id,
                    source_term="张三",
                    normalized_source_term="张三",
                    category="character",
                    source_language="zh",
                    first_seen_chapter=1,
                    last_seen_chapter=1,
                    appearance_count=1,
                    evidence_snippet="张三出现。",
                    candidate_translation_en=None,
                    normalized_target_term=None,
                    discovery_run_id="discover",
                    translation_run_id=None,
                    candidate_status="discovered",
                    validation_status="pending",
                    conflict_reason=None,
                )
            ],
        )
        upsert_translation_vote(
            conn,
            candidate_id="gcan-1",
            release_id=release_id,
            translation_run_id="translate",
            model_name="m1",
            prompt_version="v1",
            raw_output="A",
            cleaned_output="A",
            normalized_output="a",
            resolution_status="unresolved",
        )
        upsert_idiom_candidates(
            conn,
            candidates=[
                IdiomCandidate(
                    candidate_id="ican-1",
                    release_id=release_id,
                    source_text="一箭双雕",
                    normalized_source_text="一箭双雕",
                    meaning_zh="一举两得",
                    preferred_rendering_en="",
                    usage_notes=None,
                    first_seen_chapter=1,
                    last_seen_chapter=1,
                    appearance_count=1,
                    evidence_snippet="一箭双雕",
                    detection_run_id="idioms",
                    candidate_status="discovered",
                    validation_status="pending",
                    conflict_reason=None,
                    analyst_model_name="analyst",
                    analyst_prompt_version="v1",
                )
            ],
        )
        upsert_idiom_vote(
            conn,
            candidate_id="ican-1",
            release_id=release_id,
            translation_run_id="idioms",
            model_name="m1",
            prompt_version="v1",
            vote_kind="rendering",
            raw_output="A",
            cleaned_output="A",
            normalized_output="a",
            resolution_status="unresolved",
        )
    finally:
        conn.close()

    report = check_stage_gate(
        stage_name="preprocess-idioms",
        release_id=release_id,
        run_id="production",
        config=load_config(),
        chapter_start=1,
        chapter_end=1,
    )

    assert report.success is False
    assert "Unresolved glossary" in report.message()
    assert "Unresolved idiom" in report.message()


def test_translate_gate_requires_packets_for_story_chapters(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "packet-gate"
    _write_extracted_chapter(release_id)
    _seed_summary(release_id)
    _seed_graph(release_id)

    report = check_stage_gate(
        stage_name="translate-range",
        release_id=release_id,
        run_id="production",
        config=load_config(),
        chapter_start=1,
        chapter_end=1,
    )

    assert report.success is False
    assert "Missing packet inputs" in report.message()


def test_non_story_chapter_can_skip_packet_translation_and_rebuild_inputs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "non-story-gate"
    _write_extracted_chapter(release_id)
    _seed_summary(release_id, is_story=False)
    _seed_graph(release_id)

    report = check_stage_gate(
        stage_name="epub-rebuild",
        release_id=release_id,
        run_id="production",
        config=load_config(),
        chapter_start=1,
        chapter_end=1,
    )

    assert report.success is True
    assert report.metadata["story_chapter_numbers"] == []


def test_rebuild_gate_requires_translation_and_placeholders(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "rebuild-gate"
    run_id = "production"
    _seed_story_inputs(release_id, run_id)
    paths = derive_paths(load_config(), release_id=release_id)
    (paths.extracted_placeholders_dir / "chapter-1.json").unlink()

    report = check_stage_gate(
        stage_name="epub-rebuild",
        release_id=release_id,
        run_id=run_id,
        config=load_config(),
        chapter_start=1,
        chapter_end=1,
    )

    assert report.success is False
    assert "placeholder map" in report.message()


def test_unresolved_votes_ignored_for_rejected_candidates(tmp_path: Path, monkeypatch) -> None:
    """Gate should not fail for rejected candidates (llm_keep=0) with orphaned votes."""
    monkeypatch.chdir(tmp_path)
    release_id = "vote-rejected"
    _write_extracted_chapter(release_id)
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        upsert_discovered_candidates(
            conn,
            candidates=[
                GlossaryCandidate(
                    candidate_id="gcan-rejected",
                    release_id=release_id,
                    source_term="张三",
                    normalized_source_term="张三",
                    category="character",
                    source_language="zh",
                    first_seen_chapter=1,
                    last_seen_chapter=1,
                    appearance_count=1,
                    evidence_snippet="张三出现。",
                    candidate_translation_en=None,
                    normalized_target_term=None,
                    discovery_run_id="discover",
                    translation_run_id=None,
                    candidate_status="llm_rejected",
                    validation_status="pending",
                    conflict_reason=None,
                    llm_keep=0,
                )
            ],
        )
        upsert_translation_vote(
            conn,
            candidate_id="gcan-rejected",
            release_id=release_id,
            translation_run_id="translate",
            model_name="m1",
            prompt_version="v1",
            raw_output="A",
            cleaned_output="A",
            normalized_output="a",
            resolution_status="unresolved",
        )
    finally:
        conn.close()

    report = check_stage_gate(
        stage_name="preprocess-idioms",
        release_id=release_id,
        run_id="production",
        config=load_config(),
        chapter_start=1,
        chapter_end=1,
    )

    assert report.success is True
    assert "Unresolved glossary" not in report.message()


def test_no_draft_chapter_skipped_by_gate(tmp_path: Path, monkeypatch) -> None:
    """Gate should not fail for chapters with no summary_drafts row."""
    monkeypatch.chdir(tmp_path)
    release_id = "no-draft-gate"
    _write_extracted_chapter(release_id, chapter_number=1)
    _write_extracted_chapter(release_id, chapter_number=2)
    _seed_summary(release_id, chapter_number=2)  # Only chapter 2 has a draft

    report = check_stage_gate(
        stage_name="preprocess-idioms",
        release_id=release_id,
        run_id="production",
        config=load_config(),
        chapter_start=1,
        chapter_end=2,
    )

    assert report.success is True
    assert "Missing chapter story metadata" not in report.message()
    assert report.metadata.get("story_chapter_numbers") == [2]
