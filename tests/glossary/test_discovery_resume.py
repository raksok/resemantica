from __future__ import annotations

import json
from pathlib import Path

from resemantica.chapters.manifest import ChapterRef
from resemantica.db.glossary_repo import (
    ensure_glossary_schema,
    list_reusable_discovery_chapter_states,
    load_valid_discovery_chapter_state,
    replace_candidates,
    save_discovery_chapter_state,
    serialize_raw_candidates,
)
from resemantica.db.sqlite import open_connection
from resemantica.glossary.candidate_gen import CAT_FACTION, RawCandidate
from resemantica.glossary.discovery import discover_candidates_from_extracted
from resemantica.glossary.models import GlossaryCandidate
from resemantica.glossary.pipeline import discover_glossary_candidates
from resemantica.settings import derive_paths, load_config


def _write_chapter(
    root: Path,
    chapter_number: int,
    *,
    text: str,
    source_hash: str | None = None,
) -> ChapterRef:
    source_hash = source_hash or f"hash-{chapter_number}"
    chapter_path = root / f"chapter-{chapter_number}.json"
    payload = {
        "chapter_id": f"chapter-{chapter_number}",
        "chapter_number": chapter_number,
        "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
        "chapter_source_hash": source_hash,
        "records": [
            {
                "block_order": 1,
                "segment_order": None,
                "source_text_zh": text,
            }
        ],
    }
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    chapter_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return ChapterRef(
        chapter_number=chapter_number,
        chapter_path=chapter_path,
        placeholder_path=root / f"chapter-{chapter_number}-placeholders.json",
        source_document_path=f"OEBPS/chapter{chapter_number}.xhtml",
        chapter_source_hash=source_hash,
    )


def _raw(term: str, *, appearances: int = 1) -> RawCandidate:
    return RawCandidate(
        surface_form=term,
        normalized_form=term,
        pos_tags=["NN"],
        ner_label=None,
        type_prior=CAT_FACTION,
        strategies={"z_last", "a_first"},
        appearances=appearances,
        context_snippets=[term],
    )


def _candidate(release_id: str, run_id: str) -> GlossaryCandidate:
    return GlossaryCandidate(
        candidate_id="gcan_stale",
        release_id=release_id,
        source_term="旧宗",
        normalized_source_term="旧宗",
        category=CAT_FACTION,
        source_language="zh",
        first_seen_chapter=1,
        last_seen_chapter=1,
        appearance_count=1,
        evidence_snippet="旧宗",
        candidate_translation_en=None,
        normalized_target_term=None,
        discovery_run_id=run_id,
        translation_run_id=None,
        candidate_status="discovered",
        validation_status="pending",
        conflict_reason=None,
        schema_version=1,
    )


def test_chapter_state_round_trips_with_strict_input_hash() -> None:
    conn = open_connection(":memory:")
    ensure_glossary_schema(conn)
    try:
        candidate = _raw("青云门")
        save_discovery_chapter_state(
            conn,
            release_id="r1",
            run_id="run1",
            chapter_number=1,
            chapter_source_hash="src-hash",
            input_hash="input-a",
            status="completed",
            raw_candidates=[candidate],
        )
        conn.commit()

        raw_json = serialize_raw_candidates([candidate])
        assert '"strategies":["a_first","z_last"]' in raw_json

        loaded = load_valid_discovery_chapter_state(
            conn,
            release_id="r1",
            run_id="run1",
            chapter_number=1,
            chapter_source_hash="src-hash",
            input_hash="input-a",
        )
        assert loaded is not None
        assert loaded.raw_candidates[0].strategies == {"a_first", "z_last"}
        assert load_valid_discovery_chapter_state(
            conn,
            release_id="r1",
            run_id="run1",
            chapter_number=1,
            chapter_source_hash="src-hash",
            input_hash="input-b",
        ) is None
    finally:
        conn.close()


def test_resume_skips_persisted_chapter_extraction(tmp_path: Path, monkeypatch) -> None:
    refs = [
        _write_chapter(tmp_path, 1, text="青云门弟子。"),
        _write_chapter(tmp_path, 2, text="青云门长老。"),
    ]
    conn = open_connection(":memory:")
    ensure_glossary_schema(conn)
    calls: list[str] = []

    def fake_generate(text: str, summary_data=None):  # noqa: ANN001, ARG001
        calls.append(text)
        return [_raw("青云门")]

    monkeypatch.setattr("resemantica.glossary.discovery.generate_chapter_candidates", fake_generate)
    try:
        discover_candidates_from_extracted(
            release_id="r1",
            discovery_run_id="run1",
            chapter_refs=refs,
            conn=conn,
            resume=True,
        )
        assert len(calls) == 2

        def fail_generate(text: str, summary_data=None):  # noqa: ANN001, ARG001
            raise AssertionError("chapter extraction should have been reused")

        monkeypatch.setattr("resemantica.glossary.discovery.generate_chapter_candidates", fail_generate)
        discover_candidates_from_extracted(
            release_id="r1",
            discovery_run_id="run1",
            chapter_refs=refs,
            conn=conn,
            resume=True,
        )
    finally:
        conn.close()


def test_stale_source_hash_reextracts_only_affected_chapter(tmp_path: Path, monkeypatch) -> None:
    refs = [
        _write_chapter(tmp_path, 1, text="青云门弟子。", source_hash="h1"),
        _write_chapter(tmp_path, 2, text="青云门长老。", source_hash="h2"),
    ]
    conn = open_connection(":memory:")
    ensure_glossary_schema(conn)
    calls: list[str] = []

    def fake_generate(text: str, summary_data=None):  # noqa: ANN001, ARG001
        calls.append(text)
        return [_raw("青云门")]

    monkeypatch.setattr("resemantica.glossary.discovery.generate_chapter_candidates", fake_generate)
    try:
        discover_candidates_from_extracted(
            release_id="r1",
            discovery_run_id="run1",
            chapter_refs=refs,
            conn=conn,
            resume=True,
        )
        calls.clear()
        refs[1] = _write_chapter(tmp_path, 2, text="青云门掌门。", source_hash="h2-new")

        discover_candidates_from_extracted(
            release_id="r1",
            discovery_run_id="run1",
            chapter_refs=refs,
            conn=conn,
            resume=True,
        )
        assert calls == ["青云门掌门。"]
    finally:
        conn.close()


def test_skipped_chapters_are_persisted_and_reused(tmp_path: Path, monkeypatch) -> None:
    refs = [
        _write_chapter(tmp_path, 1, text="青云门弟子。"),
        _write_chapter(tmp_path, 2, text=""),
    ]
    conn = open_connection(":memory:")
    ensure_glossary_schema(conn)
    calls = 0

    def fake_generate(text: str, summary_data=None):  # noqa: ANN001, ARG001
        nonlocal calls
        calls += 1
        return [_raw("青云门")]

    monkeypatch.setattr("resemantica.glossary.discovery.generate_chapter_candidates", fake_generate)
    try:
        discover_candidates_from_extracted(
            release_id="r1",
            discovery_run_id="run1",
            chapter_refs=refs,
            skip_chapters={1},
            conn=conn,
            resume=True,
        )
        assert calls == 0
        states = list_reusable_discovery_chapter_states(conn, release_id="r1", run_id="run1")
        assert [(state.chapter_number, state.status, state.skip_reason) for state in states] == [
            (1, "skipped", "non_story"),
            (2, "skipped", "empty_text"),
        ]

        discover_candidates_from_extracted(
            release_id="r1",
            discovery_run_id="run1",
            chapter_refs=refs,
            skip_chapters={1},
            conn=conn,
            resume=True,
        )
        assert calls == 0
    finally:
        conn.close()


def test_non_story_flag_change_invalidates_completed_state(tmp_path: Path, monkeypatch) -> None:
    refs = [_write_chapter(tmp_path, 1, text="青云门弟子。")]
    conn = open_connection(":memory:")
    ensure_glossary_schema(conn)
    calls = 0

    def fake_generate(text: str, summary_data=None):  # noqa: ANN001, ARG001
        nonlocal calls
        calls += 1
        return [_raw("青云门")]

    monkeypatch.setattr("resemantica.glossary.discovery.generate_chapter_candidates", fake_generate)
    try:
        discover_candidates_from_extracted(
            release_id="r1",
            discovery_run_id="run1",
            chapter_refs=refs,
            conn=conn,
            resume=True,
        )
        assert calls == 1

        discover_candidates_from_extracted(
            release_id="r1",
            discovery_run_id="run1",
            chapter_refs=refs,
            skip_chapters={1},
            conn=conn,
            resume=True,
        )
        assert calls == 1
        states = list_reusable_discovery_chapter_states(conn, release_id="r1", run_id="run1")
        assert [(state.chapter_number, state.status, state.skip_reason) for state in states] == [
            (1, "skipped", "non_story"),
        ]
    finally:
        conn.close()


def test_replace_candidates_empty_removes_stale_rows() -> None:
    conn = open_connection(":memory:")
    ensure_glossary_schema(conn)
    try:
        replace_candidates(conn, release_id="r1", discovery_run_id="run1", candidates=[_candidate("r1", "run1")])
        assert conn.execute("SELECT COUNT(*) AS count FROM glossary_candidates").fetchone()["count"] == 1

        replace_candidates(conn, release_id="r1", discovery_run_id="run1", candidates=[])
        assert conn.execute("SELECT COUNT(*) AS count FROM glossary_candidates").fetchone()["count"] == 0
    finally:
        conn.close()


def test_force_clears_stale_discovery_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "force-resume-state"
    run_id = "discover-001"
    paths = derive_paths(load_config(), release_id=release_id)
    _write_chapter(paths.extracted_chapters_dir, 1, text="青云门弟子。")

    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        save_discovery_chapter_state(
            conn,
            release_id=release_id,
            run_id=run_id,
            chapter_number=99,
            chapter_source_hash="old",
            input_hash="old",
            status="completed",
            raw_candidates=[_raw("旧宗")],
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        "resemantica.glossary.discovery.generate_chapter_candidates",
        lambda text, summary_data=None: [_raw("青云门")],  # noqa: ARG005
    )
    monkeypatch.setattr(
        "resemantica.glossary.pipeline.deduplicate_and_cluster",
        lambda candidates, **kwargs: (candidates, []),  # noqa: ARG005
    )

    result = discover_glossary_candidates(
        release_id=release_id,
        run_id=run_id,
        skip_llm_eval=True,
        force=True,
    )
    assert result["status"] == "success"

    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        states = list_reusable_discovery_chapter_states(conn, release_id=release_id, run_id=run_id)
        assert [state.chapter_number for state in states] == [1]
    finally:
        conn.close()
