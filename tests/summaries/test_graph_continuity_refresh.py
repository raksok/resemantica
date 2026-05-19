from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from resemantica.db.graph_repo import ensure_graph_schema, save_graph_snapshot
from resemantica.db.sqlite import open_connection
from resemantica.db.summary_repo import ensure_summary_schema, get_validated_summary, save_validated_summary
from resemantica.graph.client import GraphClient, InMemoryGraphBackend
from resemantica.graph.models import GraphAlias, GraphEntity, GraphRelationship
from resemantica.settings import derive_paths, load_config
from resemantica.summaries.continuity import (
    build_graph_continuity_anchors,
    build_graph_continuity_input,
    preprocess_continuity,
)


class ScriptedContinuityLLM:
    def __init__(self, continuity_zh: str = "张三属于青云门。") -> None:
        self.continuity_zh = continuity_zh
        self.prompts: list[str] = []

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        self.prompts.append(prompt)
        if "SUMMARY_GRAPH_CONTINUITY_UPDATE" in prompt:
            return json.dumps(
                {
                    "continuity_zh": self.continuity_zh,
                    "anchor_audit": {
                        "used_entity_ids": ["ent_zhang", "ent_sect"],
                        "used_relationship_ids": ["rel_member"],
                        "uncertain_anchor_ids": [],
                        "uncertainty_notes_zh": [],
                    },
                },
                ensure_ascii=False,
            )
        if "SUMMARY_EN_DERIVE" in prompt:
            return f"EN::{self.continuity_zh}"
        raise RuntimeError("Unexpected prompt")


def _write_extracted_chapter(*, release_id: str, chapter_number: int) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "chapter_id": f"chapter-{chapter_number}",
        "chapter_number": chapter_number,
        "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
        "chapter_source_hash": f"hash-ch{chapter_number}",
        "schema_version": 1,
        "records": [
            {
                "chapter_id": f"chapter-{chapter_number}",
                "chapter_number": chapter_number,
                "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
                "block_id": f"ch{chapter_number:03d}_blk001",
                "parent_block_id": f"ch{chapter_number:03d}_blk001",
                "segment_id": None,
                "block_order": 1,
                "segment_order": None,
                "source_text_zh": f"第{chapter_number}章内容。",
                "placeholder_map_ref": "",
                "chapter_source_hash": f"hash-ch{chapter_number}",
                "schema_version": 1,
            }
        ],
    }
    (paths.extracted_chapters_dir / f"chapter-{chapter_number}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _seed_short_summary(*, release_id: str, chapter_number: int, content: str | None = None) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        save_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_short",
            content_zh=content or f"第{chapter_number}章短摘要。",
            derived_from_chapter_hash=f"hash-ch{chapter_number}",
            run_id="seed",
        )
    finally:
        conn.close()


def _seed_graph_snapshot(*, release_id: str, graph_client: GraphClient) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    snapshot = graph_client.export_snapshot(
        release_id=release_id,
        graph_db_path=paths.graph_db_path,
    )
    conn = open_connection(paths.db_path)
    ensure_graph_schema(conn)
    try:
        save_graph_snapshot(conn, snapshot=snapshot)
    finally:
        conn.close()


def _graph_client(release_id: str) -> GraphClient:
    client = GraphClient(backend=InMemoryGraphBackend())
    client.upsert_entities(
        entities=[
            GraphEntity("ent_zhang", release_id, "character", "Zhang San", None, 1, 10, 1, "confirmed"),
            GraphEntity("ent_sect", release_id, "faction", "Azure Sect", None, 1, 10, 1, "confirmed"),
        ]
    )
    client.upsert_aliases(
        aliases=[
            GraphAlias("alias_safe", release_id, "ent_zhang", "张三", "zh", 1, 10, 1, 0.9, False, "confirmed"),
            GraphAlias("alias_future", release_id, "ent_zhang", "玄天真人", "zh", 4, 10, 4, 0.9, True, "confirmed"),
        ]
    )
    client.upsert_relationships(
        relationships=[
            GraphRelationship(
                "rel_member", release_id, "MEMBER_OF", "ent_zhang", "ent_sect", 1, 1, None, 1, 0.9, "confirmed"
            ),
            GraphRelationship(
                "rel_future", release_id, "MASTER_OF", "ent_zhang", "ent_sect", 4, 4, None, 4, 0.9, "confirmed"
            ),
        ]
    )
    return client


def test_graph_anchors_exclude_future_relationships_and_aliases(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m56-anchors"
    client = _graph_client(release_id)

    anchors, audit = build_graph_continuity_anchors(graph_client=client, chapter_number=2)

    assert "张三" in anchors
    assert "玄天真人" not in anchors
    assert "rel_member" in audit["relationship_ids"]
    assert "rel_future" not in audit["relationship_ids"]
    assert "alias_safe" in audit["alias_ids"]
    assert "alias_future" not in audit["alias_ids"]


def test_refreshed_compact_continuity_includes_required_graph_anchors(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m56-refresh"
    _write_extracted_chapter(release_id=release_id, chapter_number=1)
    _seed_short_summary(release_id=release_id, chapter_number=1, content="张三拜入青云门。")
    client = _graph_client(release_id)
    _seed_graph_snapshot(release_id=release_id, graph_client=client)
    llm = ScriptedContinuityLLM()

    result = preprocess_continuity(
        release_id=release_id,
        run_id="continuity-001",
        graph_client=client,
        llm_client=llm,
    )

    assert result["status"] == "success"
    assert result["chapters_refreshed"] == 1
    prompt = next(prompt for prompt in llm.prompts if "SUMMARY_GRAPH_CONTINUITY_UPDATE" in prompt)
    assert "Zhang San" in prompt
    assert "MEMBER_OF" in prompt
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    try:
        row = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=1,
            summary_type="story_so_far_zh_graph_compact",
        )
        assert row is not None
        assert row.content_zh == "张三属于青云门。"
    finally:
        conn.close()


def test_rebase_interval_uses_previous_milestone_compact_plus_recent_summaries(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m56-rebase"
    client = _graph_client(release_id)
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        for chapter in range(1, 5):
            save_validated_summary(
                conn,
                release_id=release_id,
                chapter_number=chapter,
                summary_type="chapter_summary_zh_short",
                content_zh=f"短摘要{chapter}",
                derived_from_chapter_hash=f"hash-ch{chapter}",
                run_id="seed",
            )
        save_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=2,
            summary_type="story_so_far_zh_graph_compact",
            content_zh="第2章里程碑连续性。",
            derived_from_chapter_hash="milestone-2",
            run_id="seed",
        )
        save_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=3,
            summary_type="story_so_far_zh_graph_compact",
            content_zh="第3章普通连续性。",
            derived_from_chapter_hash="chapter-3",
            run_id="seed",
        )
        continuity_input = build_graph_continuity_input(
            conn=conn,
            release_id=release_id,
            chapter_number=4,
            graph_client=client,
            rebase_interval=2,
        )
    finally:
        conn.close()

    assert continuity_input.previous_graph_compact == "第2章里程碑连续性。"
    assert [row.chapter_number for row in continuity_input.recent_chapter_summaries] == [3, 4]


def test_output_over_token_budget_fails_clearly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m56-budget"
    _write_extracted_chapter(release_id=release_id, chapter_number=1)
    _seed_short_summary(release_id=release_id, chapter_number=1)
    client = _graph_client(release_id)
    _seed_graph_snapshot(release_id=release_id, graph_client=client)
    config = load_config()
    config.summaries.story_compact_max_tokens = 1
    monkeypatch.setattr("resemantica.summaries.continuity.count_tokens", lambda text: 2)

    with pytest.raises(ValueError, match="story_so_far_zh_graph_compact exceeds configured token budget"):
        preprocess_continuity(
            release_id=release_id,
            run_id="continuity-001",
            config=config,
            graph_client=client,
            llm_client=ScriptedContinuityLLM("很长的连续性。"),
        )


def test_missing_graph_snapshot_fails_stage_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m56-missing-snapshot"
    _write_extracted_chapter(release_id=release_id, chapter_number=1)
    _seed_short_summary(release_id=release_id, chapter_number=1)

    with pytest.raises(RuntimeError, match=re.escape(f"missing_graph_snapshot: release={release_id}")):
        preprocess_continuity(
            release_id=release_id,
            run_id="continuity-001",
            graph_client=_graph_client(release_id),
            llm_client=ScriptedContinuityLLM(),
        )
