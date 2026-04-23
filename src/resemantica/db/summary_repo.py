from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any

from resemantica.db.sqlite import apply_migrations


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _draft_id(*, release_id: str, chapter_number: int, summary_type: str) -> str:
    digest = sha256(f"{release_id}:{chapter_number}:{summary_type}".encode("utf-8")).hexdigest()[:24]
    return f"sdrf_{digest}"


def _summary_id(*, release_id: str, chapter_number: int, summary_type: str) -> str:
    digest = sha256(f"{release_id}:{chapter_number}:{summary_type}".encode("utf-8")).hexdigest()[:24]
    return f"sum_{digest}"


@dataclass(slots=True)
class SummaryDraftRecord:
    draft_id: str
    release_id: str
    chapter_number: int
    summary_type: str
    content_json: str
    chapter_source_hash: str
    model_name: str
    prompt_version: str
    run_id: str
    validation_status: str
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ValidatedSummaryZhRecord:
    summary_id: str
    release_id: str
    chapter_number: int
    summary_type: str
    content_zh: str
    derived_from_chapter_hash: str
    validation_status: str
    run_id: str
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class DerivedSummaryEnRecord:
    summary_id: str
    release_id: str
    chapter_number: int
    summary_type: str
    content_en: str
    source_summary_id: str
    source_summary_hash: str
    glossary_version_hash: str
    model_name: str
    prompt_version: str
    run_id: str
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def ensure_summary_schema(conn: sqlite3.Connection) -> None:
    migrations_dir = Path(__file__).resolve().parent / "migrations"
    apply_migrations(conn, migrations_dir)


def save_summary_draft(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    chapter_number: int,
    summary_type: str,
    content: dict[str, object],
    chapter_source_hash: str,
    model_name: str,
    prompt_version: str,
    run_id: str,
    validation_status: str,
) -> SummaryDraftRecord:
    record = SummaryDraftRecord(
        draft_id=_draft_id(
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type=summary_type,
        ),
        release_id=release_id,
        chapter_number=chapter_number,
        summary_type=summary_type,
        content_json=_canonical_json(content),
        chapter_source_hash=chapter_source_hash,
        model_name=model_name,
        prompt_version=prompt_version,
        run_id=run_id,
        validation_status=validation_status,
        schema_version=1,
    )
    with conn:
        conn.execute(
            """
            INSERT INTO summary_drafts(
                draft_id, release_id, chapter_number, summary_type, content_json,
                chapter_source_hash, model_name, prompt_version, run_id,
                validation_status, schema_version, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(release_id, chapter_number, summary_type)
            DO UPDATE SET
                content_json = excluded.content_json,
                chapter_source_hash = excluded.chapter_source_hash,
                model_name = excluded.model_name,
                prompt_version = excluded.prompt_version,
                run_id = excluded.run_id,
                validation_status = excluded.validation_status,
                schema_version = excluded.schema_version,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                record.draft_id,
                record.release_id,
                record.chapter_number,
                record.summary_type,
                record.content_json,
                record.chapter_source_hash,
                record.model_name,
                record.prompt_version,
                record.run_id,
                record.validation_status,
                record.schema_version,
            ),
        )
    return record


def set_summary_draft_status(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    chapter_number: int,
    summary_type: str,
    validation_status: str,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE summary_drafts
            SET validation_status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE release_id = ?
              AND chapter_number = ?
              AND summary_type = ?
            """,
            (validation_status, release_id, chapter_number, summary_type),
        )


def save_chapter_structured_and_short(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    chapter_number: int,
    structured_summary: dict[str, object],
    narrative_progression: str,
    derived_from_chapter_hash: str,
    run_id: str,
    validation_status: str = "approved",
) -> tuple[ValidatedSummaryZhRecord, ValidatedSummaryZhRecord]:
    structured_record = ValidatedSummaryZhRecord(
        summary_id=_summary_id(
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_structured",
        ),
        release_id=release_id,
        chapter_number=chapter_number,
        summary_type="chapter_summary_zh_structured",
        content_zh=_canonical_json(structured_summary),
        derived_from_chapter_hash=derived_from_chapter_hash,
        validation_status=validation_status,
        run_id=run_id,
        schema_version=1,
    )
    short_record = ValidatedSummaryZhRecord(
        summary_id=_summary_id(
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_short",
        ),
        release_id=release_id,
        chapter_number=chapter_number,
        summary_type="chapter_summary_zh_short",
        content_zh=narrative_progression.strip(),
        derived_from_chapter_hash=derived_from_chapter_hash,
        validation_status=validation_status,
        run_id=run_id,
        schema_version=1,
    )

    with conn:
        _upsert_validated_summary(conn, structured_record)
        _upsert_validated_summary(conn, short_record)

    return structured_record, short_record


def _upsert_validated_summary(conn: sqlite3.Connection, record: ValidatedSummaryZhRecord) -> None:
    conn.execute(
        """
        INSERT INTO validated_summaries_zh(
            summary_id, release_id, chapter_number, summary_type, content_zh,
            derived_from_chapter_hash, validation_status, run_id, schema_version, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(release_id, chapter_number, summary_type)
        DO UPDATE SET
            content_zh = excluded.content_zh,
            derived_from_chapter_hash = excluded.derived_from_chapter_hash,
            validation_status = excluded.validation_status,
            run_id = excluded.run_id,
            schema_version = excluded.schema_version,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            record.summary_id,
            record.release_id,
            record.chapter_number,
            record.summary_type,
            record.content_zh,
            record.derived_from_chapter_hash,
            record.validation_status,
            record.run_id,
            record.schema_version,
        ),
    )


def save_validated_summary(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    chapter_number: int,
    summary_type: str,
    content_zh: str,
    derived_from_chapter_hash: str,
    run_id: str,
    validation_status: str = "approved",
) -> ValidatedSummaryZhRecord:
    record = ValidatedSummaryZhRecord(
        summary_id=_summary_id(
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type=summary_type,
        ),
        release_id=release_id,
        chapter_number=chapter_number,
        summary_type=summary_type,
        content_zh=content_zh,
        derived_from_chapter_hash=derived_from_chapter_hash,
        validation_status=validation_status,
        run_id=run_id,
        schema_version=1,
    )
    with conn:
        _upsert_validated_summary(conn, record)
    return record


def _validated_from_row(row: sqlite3.Row) -> ValidatedSummaryZhRecord:
    return ValidatedSummaryZhRecord(
        summary_id=str(row["summary_id"]),
        release_id=str(row["release_id"]),
        chapter_number=int(row["chapter_number"]),
        summary_type=str(row["summary_type"]),
        content_zh=str(row["content_zh"]),
        derived_from_chapter_hash=str(row["derived_from_chapter_hash"]),
        validation_status=str(row["validation_status"]),
        run_id=str(row["run_id"]),
        schema_version=int(row["schema_version"]),
    )


def get_validated_summary(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    chapter_number: int,
    summary_type: str,
) -> ValidatedSummaryZhRecord | None:
    row = conn.execute(
        """
        SELECT summary_id, release_id, chapter_number, summary_type, content_zh,
               derived_from_chapter_hash, validation_status, run_id, schema_version
        FROM validated_summaries_zh
        WHERE release_id = ?
          AND chapter_number = ?
          AND summary_type = ?
        LIMIT 1
        """,
        (release_id, chapter_number, summary_type),
    ).fetchone()
    if row is None:
        return None
    return _validated_from_row(row)


def list_validated_summaries(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    summary_type: str | None = None,
    max_chapter_number: int | None = None,
) -> list[ValidatedSummaryZhRecord]:
    query = """
        SELECT summary_id, release_id, chapter_number, summary_type, content_zh,
               derived_from_chapter_hash, validation_status, run_id, schema_version
        FROM validated_summaries_zh
        WHERE release_id = ?
    """
    params: list[Any] = [release_id]
    if summary_type is not None:
        query += " AND summary_type = ?"
        params.append(summary_type)
    if max_chapter_number is not None:
        query += " AND chapter_number <= ?"
        params.append(max_chapter_number)
    query += " ORDER BY chapter_number, summary_type"

    rows = conn.execute(query, tuple(params)).fetchall()
    return [_validated_from_row(row) for row in rows]


def save_derived_summary(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    chapter_number: int,
    summary_type: str,
    content_en: str,
    source_summary_id: str,
    source_summary_hash: str,
    glossary_version_hash: str,
    model_name: str,
    prompt_version: str,
    run_id: str,
) -> DerivedSummaryEnRecord:
    record = DerivedSummaryEnRecord(
        summary_id=_summary_id(
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type=summary_type,
        ),
        release_id=release_id,
        chapter_number=chapter_number,
        summary_type=summary_type,
        content_en=content_en.strip(),
        source_summary_id=source_summary_id,
        source_summary_hash=source_summary_hash,
        glossary_version_hash=glossary_version_hash,
        model_name=model_name,
        prompt_version=prompt_version,
        run_id=run_id,
        schema_version=1,
    )
    with conn:
        conn.execute(
            """
            INSERT INTO derived_summaries_en(
                summary_id, release_id, chapter_number, summary_type, content_en,
                source_summary_id, source_summary_hash, glossary_version_hash,
                model_name, prompt_version, run_id, schema_version, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(release_id, chapter_number, summary_type)
            DO UPDATE SET
                content_en = excluded.content_en,
                source_summary_id = excluded.source_summary_id,
                source_summary_hash = excluded.source_summary_hash,
                glossary_version_hash = excluded.glossary_version_hash,
                model_name = excluded.model_name,
                prompt_version = excluded.prompt_version,
                run_id = excluded.run_id,
                schema_version = excluded.schema_version,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                record.summary_id,
                record.release_id,
                record.chapter_number,
                record.summary_type,
                record.content_en,
                record.source_summary_id,
                record.source_summary_hash,
                record.glossary_version_hash,
                record.model_name,
                record.prompt_version,
                record.run_id,
                record.schema_version,
            ),
        )
    return record


def _derived_from_row(row: sqlite3.Row) -> DerivedSummaryEnRecord:
    return DerivedSummaryEnRecord(
        summary_id=str(row["summary_id"]),
        release_id=str(row["release_id"]),
        chapter_number=int(row["chapter_number"]),
        summary_type=str(row["summary_type"]),
        content_en=str(row["content_en"]),
        source_summary_id=str(row["source_summary_id"]),
        source_summary_hash=str(row["source_summary_hash"]),
        glossary_version_hash=str(row["glossary_version_hash"]),
        model_name=str(row["model_name"]),
        prompt_version=str(row["prompt_version"]),
        run_id=str(row["run_id"]),
        schema_version=int(row["schema_version"]),
    )


def list_derived_summaries(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    chapter_number: int | None = None,
) -> list[DerivedSummaryEnRecord]:
    query = """
        SELECT summary_id, release_id, chapter_number, summary_type, content_en,
               source_summary_id, source_summary_hash, glossary_version_hash,
               model_name, prompt_version, run_id, schema_version
        FROM derived_summaries_en
        WHERE release_id = ?
    """
    params: list[Any] = [release_id]
    if chapter_number is not None:
        query += " AND chapter_number = ?"
        params.append(chapter_number)
    query += " ORDER BY chapter_number, summary_type"

    rows = conn.execute(query, tuple(params)).fetchall()
    return [_derived_from_row(row) for row in rows]
