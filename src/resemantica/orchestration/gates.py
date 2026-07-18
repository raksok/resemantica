from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from resemantica.settings import AppConfig, derive_paths
from resemantica.translation.completeness import audit_chapter_translation
from resemantica.utils import _read_json

_SUMMARY_TYPES = ("chapter_summary_zh_short", "story_so_far_zh")
_UNRESOLVED_STATUSES = ("pending", "unresolved")
_KNOWN_PACKET_SKIP_REASONS = {
    "empty_records",
    "non_story_chapter",
}


@dataclass(slots=True)
class GateReport:
    stage_name: str
    success: bool = True
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def fail(self, message: str) -> None:
        self.success = False
        self.failures.append(message)

    def to_dict(self) -> dict[str, object]:
        return {
            "stage_name": self.stage_name,
            "success": self.success,
            "failures": self.failures,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }

    def message(self) -> str:
        if self.success:
            return f"Gate passed for {self.stage_name}"
        return "Gate failed: " + " | ".join(self.failures)


def check_stage_gate(
    *,
    stage_name: str,
    release_id: str,
    run_id: str,
    config: AppConfig,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
) -> GateReport:
    report = GateReport(stage_name=stage_name)
    paths = derive_paths(config, release_id=release_id)

    selected = _check_extracted_inputs(
        report,
        paths=paths,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
    )
    report.metadata["chapter_numbers"] = selected

    if stage_name in {"preprocess-summaries", "preprocess-glossary"}:
        return report

    if stage_name in {
        "preprocess-idioms",
        "preprocess-graph",
        "preprocess-continuity",
        "packets-build",
        "translate-range",
        "epub-rebuild",
    }:
        _check_unresolved_preprocess_votes(report, db_path=paths.db_path, release_id=release_id)

    story_chapters: list[int] = selected
    if stage_name in {
        "preprocess-idioms",
        "preprocess-graph",
        "preprocess-continuity",
        "packets-build",
        "translate-range",
        "epub-rebuild",
    }:
        story_chapters = _check_summary_inputs(
            report,
            db_path=paths.db_path,
            summaries_dir=paths.summaries_dir,
            release_id=release_id,
            chapter_numbers=selected,
        )
        report.metadata["story_chapter_numbers"] = story_chapters

    if stage_name in {"preprocess-continuity", "packets-build", "translate-range", "epub-rebuild"}:
        _check_graph_inputs(
            report,
            db_path=paths.db_path,
            graph_snapshot_path=paths.graph_snapshot_path,
            release_id=release_id,
        )

    if stage_name in {"translate-range", "epub-rebuild"}:
        _check_packet_inputs(
            report,
            db_path=paths.db_path,
            tracking_db_path=paths.release_root / "tracking.db",
            release_id=release_id,
            run_id=run_id,
            chapter_numbers=story_chapters,
        )

    if stage_name == "epub-rebuild":
        non_story_rebuild_chapters = _non_story_chapters_with_rebuild_artifacts(
            db_path=paths.db_path,
            release_root=paths.release_root,
            release_id=release_id,
            run_id=run_id,
            chapter_numbers=selected,
            story_chapter_numbers=story_chapters,
        )
        rebuild_chapters = sorted({*story_chapters, *non_story_rebuild_chapters})
        report.metadata["rebuild_chapter_numbers"] = rebuild_chapters
        report.metadata["rebuild_non_story_chapter_numbers"] = non_story_rebuild_chapters
        _check_rebuild_inputs(
            report,
            release_root=paths.release_root,
            run_id=run_id,
            placeholders_dir=paths.extracted_placeholders_dir,
            chapter_numbers=rebuild_chapters,
        )

    return report


def _check_extracted_inputs(
    report: GateReport,
    *,
    paths: Any,
    chapter_start: int | None,
    chapter_end: int | None,
) -> list[int]:
    if chapter_start is not None and chapter_start < 1:
        report.fail("chapter_start must be >= 1")
        return []
    if chapter_end is not None and chapter_end < 1:
        report.fail("chapter_end must be >= 1")
        return []
    if chapter_start is not None and chapter_end is not None and chapter_end < chapter_start:
        report.fail("chapter_end must be greater than or equal to chapter_start")
        return []

    manifest_path = paths.extracted_chapter_manifest_path
    if not manifest_path.exists():
        report.fail(f"Missing extracted chapter manifest: {manifest_path}")
        return []

    try:
        payload = _read_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report.fail(f"Invalid extracted chapter manifest {manifest_path}: {exc}")
        return []

    rows = payload.get("chapters")
    if not isinstance(rows, list) or not rows:
        report.fail(f"Extracted chapter manifest has no chapters: {manifest_path}")
        return []

    by_number: dict[int, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            report.fail(f"Invalid chapter manifest row in {manifest_path}")
            continue
        try:
            number = int(row["chapter_number"])
        except (KeyError, TypeError, ValueError):
            report.fail(f"Invalid chapter number in manifest row: {row!r}")
            continue
        by_number[number] = row

    if not by_number:
        return []

    min_number = min(by_number)
    max_number = max(by_number)
    start = chapter_start if chapter_start is not None else min_number
    end = chapter_end if chapter_end is not None else max_number
    expected = list(range(start, end + 1))
    missing_rows = [number for number in expected if number not in by_number]
    if missing_rows:
        report.fail(f"Missing extracted chapter manifest rows: {missing_rows}")

    selected = [number for number in expected if number in by_number]
    missing_files: list[str] = []
    for number in selected:
        row = by_number[number]
        raw_path = row.get("chapter_path")
        chapter_path = Path(str(raw_path)) if raw_path else paths.extracted_chapters_dir / f"chapter-{number}.json"
        if not chapter_path.exists():
            fallback = paths.extracted_chapters_dir / f"chapter-{number}.json"
            if fallback.exists():
                chapter_path = fallback
            else:
                missing_files.append(str(chapter_path))
                continue
        try:
            chapter_payload = _read_json(chapter_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            report.fail(f"Invalid extracted chapter file {chapter_path}: {exc}")
            continue
        if int(chapter_payload.get("chapter_number", number)) != number:
            report.fail(f"Chapter file number mismatch: expected {number}, got {chapter_payload.get('chapter_number')}")

    if missing_files:
        report.fail(f"Missing extracted chapter files: {missing_files}")
    return selected


def _connect_existing(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _check_unresolved_preprocess_votes(report: GateReport, *, db_path: Path, release_id: str) -> None:
    conn = _connect_existing(db_path)
    if conn is None:
        report.metadata["unresolved_votes"] = {"glossary": 0, "idioms": 0}
        return
    try:
        glossary_count = 0
        idiom_count = 0
        glossary_examples: list[str] = []
        idiom_examples: list[str] = []
        if _table_exists(conn, "glossary_translation_votes") and _table_exists(conn, "glossary_candidates"):
            rows = conn.execute(
                """
                SELECT v.candidate_id
                FROM glossary_translation_votes v
                JOIN glossary_candidates c ON c.candidate_id = v.candidate_id
                WHERE v.release_id = ?
                  AND v.resolution_status IN (?, ?)
                  AND (c.candidate_translation_en IS NULL OR c.candidate_translation_en = '')
                  AND (c.llm_keep = 1 OR c.llm_keep IS NULL)
                ORDER BY v.candidate_id
                """,
                (release_id, *_UNRESOLVED_STATUSES),
            ).fetchall()
            glossary_count = len(rows)
            glossary_examples = [str(row["candidate_id"]) for row in rows[:5]]
        if _table_exists(conn, "idiom_translation_votes") and _table_exists(conn, "idiom_candidates"):
            rows = conn.execute(
                """
                SELECT v.candidate_id
                FROM idiom_translation_votes v
                JOIN idiom_candidates c ON c.candidate_id = v.candidate_id
                WHERE v.release_id = ?
                  AND v.resolution_status IN (?, ?)
                  AND v.vote_kind = 'rendering'
                  AND (c.preferred_rendering_en IS NULL OR c.preferred_rendering_en = '')
                ORDER BY v.candidate_id
                """,
                (release_id, *_UNRESOLVED_STATUSES),
            ).fetchall()
            idiom_count = len(rows)
            idiom_examples = [str(row["candidate_id"]) for row in rows[:5]]
    finally:
        conn.close()

    report.metadata["unresolved_votes"] = {
        "glossary": glossary_count,
        "glossary_examples": glossary_examples,
        "idioms": idiom_count,
        "idiom_examples": idiom_examples,
    }
    if glossary_count:
        report.fail(f"Unresolved glossary translation votes block downstream stages: {glossary_examples}")
    if idiom_count:
        report.fail(f"Unresolved idiom rendering votes block downstream stages: {idiom_examples}")


def _check_summary_inputs(
    report: GateReport,
    *,
    db_path: Path,
    summaries_dir: Path,
    release_id: str,
    chapter_numbers: list[int],
) -> list[int]:
    if not chapter_numbers:
        return []
    conn = _connect_existing(db_path)
    if conn is None or not _table_exists(conn, "summary_drafts") or not _table_exists(conn, "validated_summaries_zh"):
        if conn is not None:
            conn.close()
        report.fail(f"Missing summary database rows for chapters: {chapter_numbers}")
        return chapter_numbers

    story_chapters: list[int] = []
    missing_summaries: list[str] = []
    missing_artifacts: list[str] = []
    try:
        for number in chapter_numbers:
            row = conn.execute(
                """
                SELECT is_story_chapter
                FROM summary_drafts
                WHERE release_id = ?
                  AND chapter_number = ?
                  AND summary_type = 'chapter_summary_zh_structured'
                LIMIT 1
                """,
                (release_id, number),
            ).fetchone()
            if row is None:
                # No draft row — chapter was excluded by pattern or never
                # processed. Skip silently; downstream stages handle
                # gracefully.
                continue
            if int(row["is_story_chapter"]) == 0:
                continue
            story_chapters.append(number)
            for summary_type in _SUMMARY_TYPES:
                summary = conn.execute(
                    """
                    SELECT 1
                    FROM validated_summaries_zh
                    WHERE release_id = ?
                      AND chapter_number = ?
                      AND summary_type = ?
                      AND validation_status = 'approved'
                    LIMIT 1
                    """,
                    (release_id, number, summary_type),
                ).fetchone()
                if summary is None:
                    missing_summaries.append(f"chapter {number}: {summary_type}")
            for artifact_name in (f"chapter-{number}-zh.json", f"chapter-{number}-en.json"):
                artifact_path = summaries_dir / artifact_name
                if not artifact_path.exists():
                    missing_artifacts.append(str(artifact_path))
    finally:
        conn.close()

    if missing_summaries:
        report.fail(f"Missing validated summary rows: {missing_summaries}")
    if missing_artifacts:
        report.fail(f"Missing summary artifacts: {missing_artifacts}")
    return story_chapters


def _check_graph_inputs(report: GateReport, *, db_path: Path, graph_snapshot_path: Path, release_id: str) -> None:
    if not graph_snapshot_path.exists():
        report.fail(f"Missing graph snapshot artifact: {graph_snapshot_path}")
    conn = _connect_existing(db_path)
    if conn is None or not _table_exists(conn, "graph_snapshots"):
        if conn is not None:
            conn.close()
        report.fail(f"Missing graph snapshot database rows for release {release_id}")
        return
    try:
        row = conn.execute(
            "SELECT snapshot_hash FROM graph_snapshots WHERE release_id = ? LIMIT 1",
            (release_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        report.fail(f"Missing graph snapshot database rows for release {release_id}")


def _check_packet_inputs(
    report: GateReport,
    *,
    db_path: Path,
    tracking_db_path: Path,
    release_id: str,
    run_id: str,
    chapter_numbers: list[int],
) -> None:
    if not chapter_numbers:
        return
    conn = _connect_existing(db_path)
    if conn is None or not _table_exists(conn, "packet_metadata"):
        if conn is not None:
            conn.close()
        report.fail(f"Missing packet metadata for story chapters: {chapter_numbers}")
        return

    missing: list[str] = []
    try:
        for number in chapter_numbers:
            row = conn.execute(
                """
                SELECT packet_path, bundle_path
                FROM packet_metadata
                WHERE release_id = ?
                  AND chapter_number = ?
                ORDER BY built_at DESC, packet_id DESC
                LIMIT 1
                """,
                (release_id, number),
            ).fetchone()
            if row is None:
                if _has_known_packet_skip(
                    tracking_db_path,
                    release_id=release_id,
                    run_id=run_id,
                    chapter_number=number,
                ):
                    continue
                missing.append(f"chapter {number}: metadata")
                continue
            packet_path = Path(str(row["packet_path"]))
            bundle_path = Path(str(row["bundle_path"]))
            if not packet_path.exists():
                missing.append(f"chapter {number}: packet artifact {packet_path}")
            if not bundle_path.exists():
                missing.append(f"chapter {number}: bundle artifact {bundle_path}")
    finally:
        conn.close()
    if missing:
        report.fail(f"Missing packet inputs: {missing}")


def _has_known_packet_skip(
    tracking_db_path: Path,
    *,
    release_id: str,
    run_id: str,
    chapter_number: int,
) -> bool:
    conn = _connect_existing(tracking_db_path)
    if conn is None:
        return False
    if not _table_exists(conn, "events"):
        conn.close()
        return False
    try:
        rows = conn.execute(
            """
            SELECT payload_json
            FROM events
            WHERE release_id = ?
              AND run_id = ?
              AND event_type = 'packets-build.chapter_skipped'
              AND chapter_number = ?
            ORDER BY event_time DESC
            LIMIT 5
            """,
            (release_id, run_id, chapter_number),
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except json.JSONDecodeError:
                continue
            if str(payload.get("reason", "")) in _KNOWN_PACKET_SKIP_REASONS:
                return True
        return False
    finally:
        conn.close()


def _non_story_chapters_with_rebuild_artifacts(
    *,
    db_path: Path,
    release_root: Path,
    release_id: str,
    run_id: str,
    chapter_numbers: list[int],
    story_chapter_numbers: list[int],
) -> list[int]:
    candidates = sorted(set(chapter_numbers) - set(story_chapter_numbers))
    if not candidates:
        return []
    conn = _connect_existing(db_path)
    if conn is None or not _table_exists(conn, "summary_drafts"):
        if conn is not None:
            conn.close()
        return []

    translation_root = release_root / "runs" / run_id / "translation"
    non_story_chapters: list[int] = []
    try:
        for number in candidates:
            row = conn.execute(
                """
                SELECT is_story_chapter
                FROM summary_drafts
                WHERE release_id = ?
                  AND chapter_number = ?
                  AND summary_type = 'chapter_summary_zh_structured'
                LIMIT 1
                """,
                (release_id, number),
            ).fetchone()
            if row is None or int(row["is_story_chapter"]) != 0:
                continue
            translation_dir = translation_root / f"chapter-{number}"
            if (translation_dir / "pass3.json").exists() or (translation_dir / "pass2.json").exists():
                non_story_chapters.append(number)
    finally:
        conn.close()
    return non_story_chapters


def _check_rebuild_inputs(
    report: GateReport,
    *,
    release_root: Path,
    run_id: str,
    placeholders_dir: Path,
    chapter_numbers: list[int],
) -> None:
    missing: list[str] = []
    translation_root = release_root / "runs" / run_id / "translation"
    for number in chapter_numbers:
        placeholder_path = placeholders_dir / f"chapter-{number}.json"
        if not placeholder_path.exists():
            missing.append(f"chapter {number}: placeholder map {placeholder_path}")
        translation_dir = translation_root / f"chapter-{number}"
        chapter_path = release_root / "extracted" / "chapters" / f"chapter-{number}.json"
        audit = audit_chapter_translation(chapter_path, translation_dir)
        if not audit.success:
            missing.append(f"chapter {number}: incomplete translation artifact: {list(audit.errors)}")
    if missing:
        report.fail(f"Missing rebuild inputs: {missing}")
