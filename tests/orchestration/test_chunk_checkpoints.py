from __future__ import annotations

from resemantica.db.sqlite import open_connection
from resemantica.orchestration.chunk_checkpoints import (
    ChunkCheckpoint,
    checkpoint_can_be_replaced_by,
    checkpoint_covers,
    ensure_chunk_checkpoint_schema,
    last_completed_chunk,
    list_chunk_checkpoints,
    load_chunk_checkpoint,
    save_chunk_checkpoint,
)


def _checkpoint(*, chapter_start: int, chapter_end: int) -> ChunkCheckpoint:
    return ChunkCheckpoint(
        release_id="rel",
        run_id="run",
        stage_name="translate-range",
        chunk_index=0,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        status="completed",
        metadata={},
        updated_at="now",
    )


def test_chunk_checkpoint_range_compatibility() -> None:
    stored = _checkpoint(chapter_start=1, chapter_end=10)

    assert checkpoint_covers(stored, chapter_start=1, chapter_end=10)
    assert checkpoint_covers(stored, chapter_start=3, chapter_end=7)
    assert not checkpoint_covers(stored, chapter_start=7, chapter_end=12)
    assert checkpoint_can_be_replaced_by(stored, chapter_start=1, chapter_end=12)
    assert not checkpoint_can_be_replaced_by(stored, chapter_start=3, chapter_end=7)
    assert not checkpoint_can_be_replaced_by(stored, chapter_start=7, chapter_end=12)


def test_chunk_checkpoint_save_load_list_and_overwrite() -> None:
    conn = open_connection(":memory:")
    try:
        ensure_chunk_checkpoint_schema(conn)

        first = save_chunk_checkpoint(
            conn,
            release_id="rel",
            run_id="run",
            stage_name="translate-range",
            chunk_index=0,
            chapter_start=1,
            chapter_end=10,
            status="running",
            metadata={"attempt": 1},
        )
        assert first.status == "running"

        save_chunk_checkpoint(
            conn,
            release_id="rel",
            run_id="run",
            stage_name="translate-range",
            chunk_index=0,
            chapter_start=1,
            chapter_end=10,
            status="completed",
            metadata={"attempt": 2},
        )
        save_chunk_checkpoint(
            conn,
            release_id="rel",
            run_id="run",
            stage_name="translate-range",
            chunk_index=1,
            chapter_start=11,
            chapter_end=20,
            status="failed",
            metadata={"error": "boom"},
        )

        loaded = load_chunk_checkpoint(
            conn,
            release_id="rel",
            run_id="run",
            stage_name="translate-range",
            chunk_index=0,
        )
        assert loaded is not None
        assert loaded.status == "completed"
        assert loaded.metadata == {"attempt": 2}
        assert [row.chunk_index for row in list_chunk_checkpoints(
            conn,
            release_id="rel",
            run_id="run",
            stage_name="translate-range",
        )] == [0, 1]
    finally:
        conn.close()


def test_last_completed_chunk_returns_highest_completed_index() -> None:
    conn = open_connection(":memory:")
    try:
        ensure_chunk_checkpoint_schema(conn)
        for index, status in [(0, "completed"), (1, "failed"), (2, "completed")]:
            save_chunk_checkpoint(
                conn,
                release_id="rel",
                run_id="run",
                stage_name="preprocess-summaries",
                chunk_index=index,
                chapter_start=index * 10 + 1,
                chapter_end=index * 10 + 10,
                status=status,
            )

        checkpoint = last_completed_chunk(
            conn,
            release_id="rel",
            run_id="run",
            stage_name="preprocess-summaries",
        )

        assert checkpoint is not None
        assert checkpoint.chunk_index == 2
        assert checkpoint.chapter_end == 30
    finally:
        conn.close()
