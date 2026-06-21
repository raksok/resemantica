from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from resemantica.db.glossary_repo import ensure_glossary_schema, promote_locked_entries
from resemantica.db.graph_repo import ensure_graph_schema, save_graph_snapshot
from resemantica.db.sqlite import open_connection
from resemantica.db.summary_repo import (
    ensure_summary_schema,
    get_validated_summary,
    list_derived_summaries,
    save_validated_summary,
)
from resemantica.glossary.models import LockedGlossaryEntry
from resemantica.glossary.validators import normalize_term
from resemantica.graph.client import GraphClient, InMemoryGraphBackend
from resemantica.graph.models import GraphAlias, GraphEntity, GraphRelationship
from resemantica.settings import derive_paths, load_config
from resemantica.summaries.continuity import (
    build_graph_continuity_anchors,
    build_graph_continuity_input,
    preprocess_continuity,
)
from resemantica.summaries.derivation import hash_locked_glossary
from resemantica.tracking.repo import ensure_tracking_db, load_events


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


class RawGraphContinuityLLM:
    def __init__(self, graph_outputs: list[str]) -> None:
        self.graph_outputs = graph_outputs
        self.prompts: list[str] = []

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        self.prompts.append(prompt)
        if "SUMMARY_GRAPH_CONTINUITY_UPDATE" in prompt:
            return self.graph_outputs.pop(0)
        if "SUMMARY_EN_DERIVE" in prompt:
            return "EN::continuity"
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


def _seed_locked_glossary(
    *,
    release_id: str,
    rows: list[tuple[str, str, str]],
) -> list[LockedGlossaryEntry]:
    entries: list[LockedGlossaryEntry] = []
    for source_term, target_term, category in rows:
        normalized = normalize_term(source_term)
        entries.append(
            LockedGlossaryEntry(
                glossary_entry_id=f"glex_{category}_{normalized}",
                release_id=release_id,
                source_term=source_term,
                normalized_source_term=normalized,
                target_term=target_term,
                normalized_target_term=normalize_term(target_term),
                category=category,
                status="approved",
                approved_at="2026-01-01T00:00:00+00:00",
                approval_run_id="seed-glossary",
                source_candidate_id=f"gcan_{category}_{normalized}",
                schema_version=1,
            )
        )
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        with conn:
            promote_locked_entries(conn, entries=entries)
    finally:
        conn.close()
    return entries


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


def _seed_continuity_prereqs(*, release_id: str, chapters: range | list[int]) -> GraphClient:
    for chapter_number in chapters:
        _write_extracted_chapter(release_id=release_id, chapter_number=chapter_number)
        _seed_short_summary(release_id=release_id, chapter_number=chapter_number)
    client = _graph_client(release_id)
    _seed_graph_snapshot(release_id=release_id, graph_client=client)
    return client


def _chunked_config(*, chunk_size: int = 1):
    config = load_config()
    config.batch_order.enabled = True
    config.batch_order.summary_chunk_multiplier = chunk_size
    config.summaries.chapter_concurrency = 1
    return config


def _graph_continuity_cache_files(release_id: str) -> list[Path]:
    paths = derive_paths(load_config(), release_id=release_id)
    cache_dir = paths.release_root / "cache" / "llm" / "preprocess-continuity.graph-compact"
    return sorted(cache_dir.glob("*.json")) if cache_dir.exists() else []


def _replace_graph_continuity_cache_raw_output(*, release_id: str, raw_output: str) -> Path:
    cache_files = _graph_continuity_cache_files(release_id)
    assert len(cache_files) == 1
    cache_path = cache_files[0]
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["raw_output"] = raw_output
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return cache_path


def _read_graph_continuity_cache_raw_output(cache_path: Path) -> str:
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    raw_output = payload["raw_output"]
    assert isinstance(raw_output, str)
    return raw_output


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
    locked_glossary = _seed_locked_glossary(
        release_id=release_id,
        rows=[
            ("张三", "Zhang San", "character"),
            ("黑风寨", "Black Wind Fort", "faction"),
        ],
    )
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
    en_prompt = next(prompt for prompt in llm.prompts if "SUMMARY_EN_DERIVE" in prompt)
    assert "- 张三 => Zhang San" in en_prompt
    assert "黑风寨" not in en_prompt
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
        derived_rows = list_derived_summaries(conn, release_id=release_id, chapter_number=1)
        graph_en = next(row for row in derived_rows if row.summary_type == "story_so_far_en_graph_compact")
        assert graph_en.glossary_version_hash == hash_locked_glossary(locked_glossary)
    finally:
        conn.close()


def test_chunked_continuity_runs_analyst_then_translator_per_chunk(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m69-model-order"
    client = _seed_continuity_prereqs(release_id=release_id, chapters=range(1, 6))
    config = load_config()
    config.batch_order.enabled = True
    config.batch_order.summary_chunk_multiplier = 1
    config.summaries.chapter_concurrency = 2
    llm = ScriptedContinuityLLM()

    preprocess_continuity(
        release_id=release_id,
        run_id="continuity-001",
        config=config,
        graph_client=client,
        llm_client=llm,
    )

    kinds = [
        "analyst" if "SUMMARY_GRAPH_CONTINUITY_UPDATE" in prompt else "translator"
        for prompt in llm.prompts
    ]
    assert kinds == [
        "analyst",
        "analyst",
        "translator",
        "translator",
        "analyst",
        "analyst",
        "translator",
        "translator",
        "analyst",
        "translator",
    ]


def test_completed_continuity_chunk_resume_skips_when_rows_and_artifacts_complete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m69-completed-skip"
    client = _seed_continuity_prereqs(release_id=release_id, chapters=[1, 2])
    config = _chunked_config(chunk_size=1)

    preprocess_continuity(
        release_id=release_id,
        run_id="continuity-001",
        config=config,
        graph_client=client,
        llm_client=ScriptedContinuityLLM(),
    )
    llm = ScriptedContinuityLLM("should-not-run")

    result = preprocess_continuity(
        release_id=release_id,
        run_id="continuity-001",
        config=config,
        graph_client=client,
        llm_client=llm,
    )

    assert result["chapters_refreshed"] == 0
    assert llm.prompts == []


def test_chunked_continuity_backfills_english_from_current_graph_rows_without_analyst(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m69-en-backfill"
    client = _seed_continuity_prereqs(release_id=release_id, chapters=[1, 2])
    config = _chunked_config(chunk_size=1)
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        for chapter_number in [1, 2]:
            continuity_input = build_graph_continuity_input(
                conn=conn,
                release_id=release_id,
                chapter_number=chapter_number,
                graph_client=client,
                rebase_interval=config.summaries.graph_continuity_rebase_interval,
            )
            save_validated_summary(
                conn,
                release_id=release_id,
                chapter_number=chapter_number,
                summary_type="story_so_far_zh_graph_compact",
                content_zh=f"已有第{chapter_number}章图谱连续性。",
                derived_from_chapter_hash=continuity_input.source_hash,
                run_id="seed",
            )
    finally:
        conn.close()
    llm = ScriptedContinuityLLM("should-not-generate-zh")

    preprocess_continuity(
        release_id=release_id,
        run_id="continuity-001",
        config=config,
        graph_client=client,
        llm_client=llm,
    )

    assert sum("SUMMARY_GRAPH_CONTINUITY_UPDATE" in prompt for prompt in llm.prompts) == 0
    assert sum("SUMMARY_EN_DERIVE" in prompt for prompt in llm.prompts) == 2


def test_chunked_continuity_regenerates_stale_graph_compact_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m69-stale-zh"
    client = _seed_continuity_prereqs(release_id=release_id, chapters=[1, 2])
    config = _chunked_config(chunk_size=1)
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_summary_schema(conn)
    try:
        save_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=1,
            summary_type="story_so_far_zh_graph_compact",
            content_zh="旧图谱连续性。",
            derived_from_chapter_hash="stale-source-hash",
            run_id="seed",
        )
    finally:
        conn.close()
    llm = ScriptedContinuityLLM("新图谱连续性。")

    preprocess_continuity(
        release_id=release_id,
        run_id="continuity-001",
        config=config,
        graph_client=client,
        llm_client=llm,
    )

    assert sum("SUMMARY_GRAPH_CONTINUITY_UPDATE" in prompt for prompt in llm.prompts) >= 1
    conn = open_connection(paths.db_path)
    try:
        row = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=1,
            summary_type="story_so_far_zh_graph_compact",
        )
    finally:
        conn.close()
    assert row is not None
    assert row.derived_from_chapter_hash != "stale-source-hash"
    assert row.content_zh == "新图谱连续性。"


def test_chunked_continuity_failure_records_chunk_failed_event_and_checkpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m69-chunk-failed"
    client = _seed_continuity_prereqs(release_id=release_id, chapters=[1, 2])
    config = _chunked_config(chunk_size=1)

    with pytest.raises(ValueError, match="graph_continuity_output_invalid: empty model output"):
        preprocess_continuity(
            release_id=release_id,
            run_id="continuity-001",
            config=config,
            graph_client=client,
            llm_client=RawGraphContinuityLLM([""]),
        )

    tracking = ensure_tracking_db(release_id)
    try:
        events = load_events(tracking, run_id="continuity-001", release_id=release_id, limit=100)
    finally:
        tracking.close()
    assert any(event.event_type == "preprocess-continuity.chunk_failed" for event in events)

    from resemantica.orchestration.chunk_checkpoints import load_chunk_checkpoint

    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    try:
        checkpoint = load_chunk_checkpoint(
            conn,
            release_id=release_id,
            run_id="continuity-001",
            stage_name="preprocess-continuity",
            chunk_index=0,
        )
    finally:
        conn.close()
    assert checkpoint is not None
    assert checkpoint.status == "failed"


def test_empty_cached_graph_continuity_output_is_regenerated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m68-empty-cache"
    _write_extracted_chapter(release_id=release_id, chapter_number=1)
    _seed_short_summary(release_id=release_id, chapter_number=1)
    client = _graph_client(release_id)
    _seed_graph_snapshot(release_id=release_id, graph_client=client)

    preprocess_continuity(
        release_id=release_id,
        run_id="continuity-seed",
        graph_client=client,
        llm_client=ScriptedContinuityLLM("旧连续性。"),
    )
    cache_path = _replace_graph_continuity_cache_raw_output(release_id=release_id, raw_output="")
    llm = ScriptedContinuityLLM("再生成的连续性。")

    result = preprocess_continuity(
        release_id=release_id,
        run_id="continuity-retry",
        graph_client=client,
        llm_client=llm,
    )

    assert result["status"] == "success"
    assert sum("SUMMARY_GRAPH_CONTINUITY_UPDATE" in prompt for prompt in llm.prompts) == 1
    assert "再生成的连续性。" in _read_graph_continuity_cache_raw_output(cache_path)


def test_fresh_empty_graph_continuity_output_fails_without_cache_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m68-fresh-empty"
    _write_extracted_chapter(release_id=release_id, chapter_number=1)
    _seed_short_summary(release_id=release_id, chapter_number=1)
    client = _graph_client(release_id)
    _seed_graph_snapshot(release_id=release_id, graph_client=client)

    with pytest.raises(ValueError, match="graph_continuity_output_invalid: empty model output"):
        preprocess_continuity(
            release_id=release_id,
            run_id="continuity-001",
            graph_client=client,
            llm_client=RawGraphContinuityLLM([""]),
        )

    assert _graph_continuity_cache_files(release_id) == []


def test_malformed_cached_graph_continuity_output_is_regenerated_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m68-malformed-cache"
    _write_extracted_chapter(release_id=release_id, chapter_number=1)
    _seed_short_summary(release_id=release_id, chapter_number=1)
    client = _graph_client(release_id)
    _seed_graph_snapshot(release_id=release_id, graph_client=client)

    preprocess_continuity(
        release_id=release_id,
        run_id="continuity-seed",
        graph_client=client,
        llm_client=ScriptedContinuityLLM("旧连续性。"),
    )
    cache_path = _replace_graph_continuity_cache_raw_output(release_id=release_id, raw_output="{")
    llm = ScriptedContinuityLLM("修复后的连续性。")

    preprocess_continuity(
        release_id=release_id,
        run_id="continuity-retry",
        graph_client=client,
        llm_client=llm,
    )

    assert sum("SUMMARY_GRAPH_CONTINUITY_UPDATE" in prompt for prompt in llm.prompts) == 1
    assert "修复后的连续性。" in _read_graph_continuity_cache_raw_output(cache_path)


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

    tracking = ensure_tracking_db(release_id)
    try:
        events = load_events(tracking, run_id="continuity-001", release_id=release_id, limit=100)
    finally:
        tracking.close()
    failed = [event for event in events if event.event_type == "preprocess-continuity.chapter_failed"]
    assert len(failed) == 1
    assert failed[0].chapter_number == 1
    assert failed[0].severity == "error"
    assert "story_so_far_zh_graph_compact exceeds configured token budget" in failed[0].payload["reason"]


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
