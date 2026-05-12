from __future__ import annotations

import sqlite3

from resemantica.db.sqlite import ensure_schema, open_connection
from resemantica.translation.checkpoints import (
    load_checkpoint,
    save_checkpoint,
)


def _conn(tmp_path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    conn = open_connection(db_path)
    ensure_schema(conn, "translation")
    return conn


def test_save_and_load_with_hash(tmp_path) -> None:
    conn = _conn(tmp_path)
    saved = save_checkpoint(
        conn,
        release_id="r1",
        run_id="run1",
        chapter_number=1,
        pass_name="pass1",
        source_hash="abc",
        prompt_version="v1",
        packet_version_hash="packet_hash_123",
        status="success",
        artifact_path="/tmp/artifact.json",
    )
    assert saved.packet_version_hash == "packet_hash_123"

    loaded = load_checkpoint(
        conn,
        release_id="r1",
        run_id="run1",
        chapter_number=1,
        pass_name="pass1",
        source_hash="abc",
        prompt_version="v1",
        packet_version_hash="packet_hash_123",
    )
    assert loaded is not None
    assert loaded.packet_version_hash == "packet_hash_123"
    assert loaded.status == "success"
    conn.close()


def test_load_with_wrong_hash_returns_none(tmp_path) -> None:
    conn = _conn(tmp_path)
    save_checkpoint(
        conn,
        release_id="r1",
        run_id="run1",
        chapter_number=1,
        pass_name="pass1",
        source_hash="abc",
        prompt_version="v1",
        packet_version_hash="correct_hash",
        status="success",
        artifact_path="/tmp/artifact.json",
    )
    loaded = load_checkpoint(
        conn,
        release_id="r1",
        run_id="run1",
        chapter_number=1,
        pass_name="pass1",
        source_hash="abc",
        prompt_version="v1",
        packet_version_hash="wrong_hash",
    )
    assert loaded is None
    conn.close()


def test_load_with_empty_hash_against_stored_hash(tmp_path) -> None:
    conn = _conn(tmp_path)
    save_checkpoint(
        conn,
        release_id="r1",
        run_id="run1",
        chapter_number=1,
        pass_name="pass1",
        source_hash="abc",
        prompt_version="v1",
        packet_version_hash="stored_hash",
        status="success",
        artifact_path="/tmp/artifact.json",
    )
    loaded = load_checkpoint(
        conn,
        release_id="r1",
        run_id="run1",
        chapter_number=1,
        pass_name="pass1",
        source_hash="abc",
        prompt_version="v1",
        packet_version_hash="",
    )
    assert loaded is None
    conn.close()


def test_save_overwrites_previous_checkpoint(tmp_path) -> None:
    conn = _conn(tmp_path)
    save_checkpoint(
        conn,
        release_id="r1",
        run_id="run1",
        chapter_number=1,
        pass_name="pass1",
        source_hash="abc",
        prompt_version="v1",
        packet_version_hash="old_hash",
        status="success",
        artifact_path="/tmp/old.json",
    )
    save_checkpoint(
        conn,
        release_id="r1",
        run_id="run1",
        chapter_number=1,
        pass_name="pass1",
        source_hash="abc",
        prompt_version="v1",
        packet_version_hash="new_hash",
        status="success",
        artifact_path="/tmp/new.json",
    )
    loaded = load_checkpoint(
        conn,
        release_id="r1",
        run_id="run1",
        chapter_number=1,
        pass_name="pass1",
        source_hash="abc",
        prompt_version="v1",
        packet_version_hash="new_hash",
    )
    assert loaded is not None
    assert loaded.packet_version_hash == "new_hash"
    assert loaded.artifact_path == "/tmp/new.json"

    old = load_checkpoint(
        conn,
        release_id="r1",
        run_id="run1",
        chapter_number=1,
        pass_name="pass1",
        source_hash="abc",
        prompt_version="v1",
        packet_version_hash="old_hash",
    )
    assert old is None
    conn.close()


def test_default_hash_on_save(tmp_path) -> None:
    conn = _conn(tmp_path)
    saved = save_checkpoint(
        conn,
        release_id="r1",
        run_id="run1",
        chapter_number=1,
        pass_name="pass1",
        source_hash="abc",
        prompt_version="v1",
        status="success",
        artifact_path="/tmp/artifact.json",
    )
    assert saved.packet_version_hash == ""

    loaded = load_checkpoint(
        conn,
        release_id="r1",
        run_id="run1",
        chapter_number=1,
        pass_name="pass1",
        source_hash="abc",
        prompt_version="v1",
        packet_version_hash="",
    )
    assert loaded is not None
    conn.close()
