from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Literal

from resemantica.db.glossary_repo import list_locked_entries
from resemantica.db.sqlite import ensure_schema, open_connection
from resemantica.db.summary_repo import (
    get_summary_checkpoint,
    get_validated_summary,
    list_derived_summaries,
    set_summary_checkpoint,
)
from resemantica.llm.prompts import load_prompt
from resemantica.orchestration.chunk_checkpoints import list_chunk_checkpoints
from resemantica.orchestration.events import emit_event
from resemantica.orchestration.models import StageResult
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.summaries.derivation import hash_locked_glossary, hash_validated_summary
from resemantica.tracking.repo import (
    ensure_tracking_db,
    load_events,
    load_run_state,
    save_run_state,
)
from resemantica.translation.completeness import audit_chapter_translation

RetryStage = Literal[
    "preprocess-summaries",
    "preprocess-glossary",
    "preprocess-idioms",
    "preprocess-graph",
    "preprocess-continuity",
    "packets-build",
    "translate-range",
]

SUPPORTED_RETRY_STAGES: tuple[RetryStage, ...] = (
    "preprocess-summaries",
    "preprocess-glossary",
    "preprocess-idioms",
    "preprocess-graph",
    "preprocess-continuity",
    "packets-build",
    "translate-range",
)
_CHAPTER_FILE_RE = re.compile(r"chapter-(\d+)\.json$")


@dataclass(slots=True)
class RetryUnit:
    stage: str
    chapter_start: int | None
    chapter_end: int | None
    reason: str
    chapters: list[int] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RetryFailedPlan:
    release_id: str
    run_id: str
    stage: str
    retryable: list[RetryUnit] = field(default_factory=list)
    non_retryable: list[RetryUnit] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "release_id": self.release_id,
            "run_id": self.run_id,
            "stage": self.stage,
            "retryable": [item.to_dict() for item in self.retryable],
            "non_retryable": [item.to_dict() for item in self.non_retryable],
        }


def _scope_bounds(
    *,
    chapter: int | None,
    chapter_start: int | None,
    chapter_end: int | None,
) -> tuple[int | None, int | None]:
    if chapter is not None:
        return chapter, chapter
    return chapter_start, chapter_end


def _scoped_numbers(numbers: Iterable[int], start: int | None, end: int | None) -> list[int]:
    return sorted(
        number
        for number in set(numbers)
        if (start is None or number >= start) and (end is None or number <= end)
    )


def _chapter_number_from_file(path: Path) -> int | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        payload = {}
    if isinstance(payload, dict):
        value = payload.get("chapter_number")
        if isinstance(value, int):
            return value
    match = _CHAPTER_FILE_RE.match(path.name)
    return int(match.group(1)) if match is not None else None


def _list_extracted_chapter_numbers(
    *,
    config: AppConfig,
    release_id: str,
    start: int | None,
    end: int | None,
) -> list[int]:
    paths = derive_paths(config, release_id=release_id)
    if not paths.extracted_chapters_dir.exists():
        return []
    numbers = [
        number
        for path in paths.extracted_chapters_dir.glob("chapter-*.json")
        if (number := _chapter_number_from_file(path)) is not None
    ]
    return _scoped_numbers(numbers, start, end)


def _list_extracted_chapter_hashes(
    *,
    config: AppConfig,
    release_id: str,
    start: int | None,
    end: int | None,
) -> dict[int, str]:
    paths = derive_paths(config, release_id=release_id)
    if not paths.extracted_chapters_dir.exists():
        return {}
    chapter_hashes: dict[int, str] = {}
    for path in paths.extracted_chapters_dir.glob("chapter-*.json"):
        number = _chapter_number_from_file(path)
        if number is None:
            continue
        if (start is not None and number < start) or (end is not None and number > end):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
        chapter_source_hash = ""
        if isinstance(payload, dict):
            chapter_source_hash = str(payload.get("chapter_source_hash") or "")
        chapter_hashes[number] = chapter_source_hash
    return dict(sorted(chapter_hashes.items()))


def _command(
    *,
    release_id: str,
    run_id: str,
    stage: str,
    start: int | None,
    end: int | None,
) -> str:
    parts = [
        "uv",
        "run",
        "python",
        "-m",
        "resemantica.cli",
        "run",
        "retry-failed",
        "-r",
        release_id,
        "-R",
        run_id,
        "--stage",
        stage,
    ]
    if start is not None and end is not None and start == end:
        parts.extend(["--chapter", str(start)])
    else:
        if start is not None:
            parts.extend(["--start", str(start)])
        if end is not None:
            parts.extend(["--end", str(end)])
    return " ".join(parts)


def _unit(
    *,
    release_id: str,
    run_id: str,
    stage: str,
    chapters: list[int],
    reason: str,
    start: int | None = None,
    end: int | None = None,
) -> RetryUnit:
    resolved_start = start if start is not None else (min(chapters) if chapters else None)
    resolved_end = end if end is not None else (max(chapters) if chapters else None)
    return RetryUnit(
        stage=stage,
        chapter_start=resolved_start,
        chapter_end=resolved_end,
        reason=reason,
        chapters=chapters,
        commands=[
            _command(
                release_id=release_id,
                run_id=run_id,
                stage=stage,
                start=resolved_start,
                end=resolved_end,
            )
        ],
    )


def _query_ints(conn: sqlite3.Connection, query: str, params: tuple[object, ...]) -> list[int]:
    try:
        rows = conn.execute(query, params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [int(row[0]) for row in rows if row[0] is not None]


def _failed_summary_categories(
    conn: sqlite3.Connection,
    *,
    release_id: str,
    chapters: list[int],
) -> set[str]:
    if not chapters:
        return set()
    placeholders = ",".join("?" for _ in chapters)
    try:
        rows = conn.execute(
            f"""
            SELECT content_json
            FROM summary_drafts
            WHERE release_id = ?
              AND summary_type = 'chapter_summary_zh_structured'
              AND validation_status = 'failed'
              AND chapter_number IN ({placeholders})
            """,
            (release_id, *chapters),
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    categories: set[str] = set()
    for row in rows:
        try:
            payload = json.loads(str(row["content_json"]))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            category = payload.get("failure_category")
            if isinstance(category, str) and category.strip():
                categories.add(category)
    return categories


def _plan_summaries(
    *,
    conn: sqlite3.Connection,
    release_id: str,
    run_id: str,
    config: AppConfig,
    start: int | None,
    end: int | None,
) -> tuple[list[RetryUnit], list[RetryUnit]]:
    extracted = _list_extracted_chapter_numbers(
        config=config,
        release_id=release_id,
        start=start,
        end=end,
    )
    failed = _query_ints(
        conn,
        """
        SELECT chapter_number
        FROM summary_drafts
        WHERE release_id = ?
          AND summary_type = 'chapter_summary_zh_structured'
          AND validation_status = 'failed'
        """,
        (release_id,),
    )
    missing: list[int] = []
    for number in extracted:
        row = conn.execute(
            """
            SELECT validation_status, is_story_chapter
            FROM summary_drafts
            WHERE release_id = ?
              AND chapter_number = ?
              AND summary_type = 'chapter_summary_zh_structured'
            LIMIT 1
            """,
            (release_id, number),
        ).fetchone()
        if row is not None and int(row["is_story_chapter"]) == 0:
            continue
        structured = conn.execute(
            """
            SELECT 1
            FROM validated_summaries_zh
            WHERE release_id = ?
              AND chapter_number = ?
              AND summary_type = 'chapter_summary_zh_structured'
              AND validation_status = 'approved'
            LIMIT 1
            """,
            (release_id, number),
        ).fetchone()
        short = conn.execute(
            """
            SELECT 1
            FROM validated_summaries_zh
            WHERE release_id = ?
              AND chapter_number = ?
              AND summary_type = 'chapter_summary_zh_short'
              AND validation_status = 'approved'
            LIMIT 1
            """,
            (release_id, number),
        ).fetchone()
        if structured is None or short is None:
            missing.append(number)
    affected = _scoped_numbers([*failed, *missing], start, end)
    if not affected:
        return [], []
    retry_end = end if end is not None else (max(extracted) if extracted else max(affected))
    categories = _failed_summary_categories(conn, release_id=release_id, chapters=affected)
    missing_without_failed = set(missing) - set(failed)
    reason = (
        "llm_content_validation_failed"
        if categories == {"llm_content_validation_failed"} and not missing_without_failed
        else "failed_or_missing_summary_rows"
    )
    return [
        _unit(
            release_id=release_id,
            run_id=run_id,
            stage="preprocess-summaries",
            chapters=affected,
            reason=reason,
            start=min(affected),
            end=retry_end,
        )
    ], []


def _plan_candidate_stage(
    *,
    conn: sqlite3.Connection,
    release_id: str,
    run_id: str,
    table: str,
    stage: str,
    conflict_table: str,
) -> tuple[list[RetryUnit], list[RetryUnit]]:
    retryable_count = 0
    conflict_count = 0
    try:
        retryable_count = int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM {table}
                WHERE release_id = ?
                  AND candidate_status NOT IN ('promoted', 'approved', 'conflict', 'alias_merged', 'pruned')
                """,
                (release_id,),
            ).fetchone()[0]
        )
        conflict_count = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {conflict_table} WHERE release_id = ?",
                (release_id,),
            ).fetchone()[0]
        )
    except sqlite3.OperationalError:
        return [], []

    retryable = [
        _unit(
            release_id=release_id,
            run_id=run_id,
            stage=stage,
            chapters=[],
            reason="incomplete_translation_or_promotion_state",
        )
    ] if retryable_count else []
    non_retryable = [
        RetryUnit(
            stage=stage,
            chapter_start=None,
            chapter_end=None,
            reason=f"{conflict_count} conflict(s) require review",
        )
    ] if conflict_count else []
    return retryable, non_retryable


def _plan_graph(
    *,
    conn: sqlite3.Connection,
    release_id: str,
    run_id: str,
    config: AppConfig,
    start: int | None,
    end: int | None,
) -> tuple[list[RetryUnit], list[RetryUnit]]:
    chapter_hashes = _list_extracted_chapter_hashes(
        config=config,
        release_id=release_id,
        start=start,
        end=end,
    )
    prompt_version = load_prompt("graph_extract.txt").version
    missing = []
    for chapter_number, chapter_source_hash in chapter_hashes.items():
        try:
            row = conn.execute(
                """
                SELECT 1 FROM graph_extraction_drafts
                WHERE release_id = ?
                  AND run_id = ?
                  AND chapter_number = ?
                  AND chapter_source_hash = ?
                  AND prompt_version = ?
                LIMIT 1
                """,
                (release_id, run_id, chapter_number, chapter_source_hash, prompt_version),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row is None:
            missing.append(chapter_number)
    if not missing:
        failed_events = _graph_failed_event_chapters(release_id, run_id, start, end)
        missing = failed_events
    if not missing:
        return [], []
    return [
        _unit(
            release_id=release_id,
            run_id=run_id,
            stage="preprocess-graph",
            chapters=missing,
            reason="missing_or_stale_graph_draft_or_failed_validation",
        )
    ], []


def _failed_event_chapters(
    release_id: str,
    run_id: str,
    stage: str,
    start: int | None,
    end: int | None,
) -> list[int]:
    tracking = ensure_tracking_db(release_id)
    try:
        events = load_events(tracking, run_id=run_id, release_id=release_id, limit=10000)
    finally:
        tracking.close()
    numbers = [
        int(event.chapter_number)
        for event in events
        if event.chapter_number is not None
        and event.stage_name == stage
        and event.event_type.endswith(".failed")
    ]
    return _scoped_numbers(numbers, start, end)


def _graph_failed_event_chapters(
    release_id: str,
    run_id: str,
    start: int | None,
    end: int | None,
) -> list[int]:
    tracking = ensure_tracking_db(release_id)
    try:
        events = load_events(tracking, run_id=run_id, release_id=release_id, limit=10000)
    finally:
        tracking.close()
    numbers = [
        int(event.chapter_number)
        for event in events
        if event.chapter_number is not None
        and event.stage_name == "preprocess-graph"
        and (
            event.event_type.endswith(".failed")
            or event.event_type == "preprocess-graph.validation_failed"
        )
    ]
    return _scoped_numbers(numbers, start, end)


def _plan_packets(
    *,
    conn: sqlite3.Connection,
    release_id: str,
    run_id: str,
    config: AppConfig,
    start: int | None,
    end: int | None,
) -> tuple[list[RetryUnit], list[RetryUnit]]:
    chapters = _list_extracted_chapter_numbers(
        config=config,
        release_id=release_id,
        start=start,
        end=end,
    )
    missing = []
    for chapter_number in chapters:
        try:
            row = conn.execute(
                """
                SELECT 1 FROM packet_metadata
                WHERE release_id = ? AND run_id = ? AND chapter_number = ?
                LIMIT 1
                """,
                (release_id, run_id, chapter_number),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row is None:
            missing.append(chapter_number)
    failed = _failed_event_chapters(release_id, run_id, "packets-build", start, end)
    affected = _scoped_numbers([*missing, *failed], start, end)
    if not affected:
        return [], []
    return [
        _unit(
            release_id=release_id,
            run_id=run_id,
            stage="packets-build",
            chapters=affected,
            reason="missing_packet_metadata_or_chapter_failed_event",
        )
    ], []


def _plan_continuity(
    *,
    conn: sqlite3.Connection,
    release_id: str,
    run_id: str,
    config: AppConfig,
    start: int | None,
    end: int | None,
) -> tuple[list[RetryUnit], list[RetryUnit]]:
    chapters = _list_extracted_chapter_numbers(
        config=config,
        release_id=release_id,
        start=start,
        end=end,
    )
    paths = derive_paths(config, release_id=release_id)
    locked_glossary = list_locked_entries(conn, release_id=release_id)
    glossary_hash = hash_locked_glossary(locked_glossary)
    missing = []
    for chapter_number in chapters:
        zh_record = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="story_so_far_zh_graph_compact",
        )
        if zh_record is None:
            missing.append(chapter_number)
            continue

        expected_source_hash = hash_validated_summary(zh_record)
        english_current = any(
            row.summary_type == "story_so_far_en_graph_compact"
            and row.source_summary_id == zh_record.summary_id
            and row.source_summary_hash == expected_source_hash
            and row.glossary_version_hash == glossary_hash
            for row in list_derived_summaries(conn, release_id=release_id, chapter_number=chapter_number)
        )
        artifact_path = paths.summaries_dir / f"chapter-{chapter_number}-graph-continuity.json"
        if not english_current or not artifact_path.exists():
            missing.append(chapter_number)
    failed = _failed_event_chapters(release_id, run_id, "preprocess-continuity", start, end)
    failed_chunks: list[int] = []
    try:
        checkpoints = list_chunk_checkpoints(
            conn,
            release_id=release_id,
            run_id=run_id,
            stage_name="preprocess-continuity",
        )
    except sqlite3.OperationalError:
        checkpoints = []
    chapter_set = set(chapters)
    for checkpoint in checkpoints:
        if checkpoint.status != "failed":
            continue
        failed_chunks.extend(
            chapter
            for chapter in chapters
            if chapter in chapter_set
            and checkpoint.chapter_start <= chapter <= checkpoint.chapter_end
        )
    affected = _scoped_numbers([*missing, *failed, *failed_chunks], start, end)
    if not affected:
        return [], []
    return [
        _unit(
            release_id=release_id,
            run_id=run_id,
            stage="preprocess-continuity",
            chapters=affected,
            reason="missing_or_stale_graph_continuity_rows_artifacts_or_failed_event",
        )
    ], []


def _plan_translation(
    *,
    conn: sqlite3.Connection,
    release_id: str,
    run_id: str,
    config: AppConfig,
    start: int | None,
    end: int | None,
) -> tuple[list[RetryUnit], list[RetryUnit]]:
    final_pass_name = "pass3" if config.translation.pass3_default else "pass2"
    failed = _query_ints(
        conn,
        """
        SELECT DISTINCT chapter_number
        FROM translation_checkpoints
        WHERE release_id = ?
          AND run_id = ?
          AND pass_name IN ('pass1', ?)
          AND status = 'failed'
        """,
        (release_id, run_id, final_pass_name),
    )
    chapters = _list_extracted_chapter_numbers(
        config=config,
        release_id=release_id,
        start=start,
        end=end,
    )
    for chapter_number in chapters:
        try:
            row = conn.execute(
                """
                SELECT 1 FROM translation_checkpoints
                WHERE release_id = ?
                  AND run_id = ?
                  AND chapter_number = ?
                  AND pass_name = ?
                  AND status = 'success'
                LIMIT 1
                """,
                (release_id, run_id, chapter_number, final_pass_name),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row is None:
            failed.append(chapter_number)
            continue
        paths = derive_paths(config, release_id=release_id)
        chapter_path = paths.extracted_chapters_dir / f"chapter-{chapter_number}.json"
        try:
            chapter_payload = json.loads(chapter_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            failed.append(chapter_number)
            continue
        if chapter_payload.get("records"):
            translation_dir = (
                paths.release_root
                / "runs"
                / run_id
                / "translation"
                / f"chapter-{chapter_number}"
            )
            if not audit_chapter_translation(chapter_path, translation_dir).success:
                failed.append(chapter_number)
    affected = _scoped_numbers(failed, start, end)
    if not affected:
        return [], []
    return [
        _unit(
            release_id=release_id,
            run_id=run_id,
            stage="translate-range",
            chapters=affected,
            reason="failed_or_incomplete_translation_checkpoint",
        )
    ], []


def plan_retry_failed(
    *,
    release_id: str,
    run_id: str,
    stage: str = "all",
    chapter: int | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    config: AppConfig | None = None,
) -> RetryFailedPlan:
    if stage != "all" and stage not in SUPPORTED_RETRY_STAGES:
        raise ValueError(f"Unsupported retry stage: {stage}")
    start, end = _scope_bounds(chapter=chapter, chapter_start=chapter_start, chapter_end=chapter_end)
    if start is not None and end is not None and end < start:
        raise ValueError("chapter end must be greater than or equal to chapter start")
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id)
    conn = open_connection(paths.db_path)
    try:
        for schema in ("summaries", "glossary", "idioms", "graph", "packets", "translation", "chunk_checkpoints"):
            try:
                ensure_schema(conn, schema)
            except Exception:
                pass
        selected: tuple[str, ...] = SUPPORTED_RETRY_STAGES if stage == "all" else (stage,)
        plan = RetryFailedPlan(release_id=release_id, run_id=run_id, stage=stage)
        for selected_stage in selected:
            if selected_stage == "preprocess-summaries":
                retryable, non_retryable = _plan_summaries(
                    conn=conn,
                    release_id=release_id,
                    run_id=run_id,
                    config=config_obj,
                    start=start,
                    end=end,
                )
            elif selected_stage == "preprocess-glossary":
                retryable, non_retryable = _plan_candidate_stage(
                    conn=conn,
                    release_id=release_id,
                    run_id=run_id,
                    table="glossary_candidates",
                    conflict_table="glossary_conflicts",
                    stage=selected_stage,
                )
            elif selected_stage == "preprocess-idioms":
                retryable, non_retryable = _plan_candidate_stage(
                    conn=conn,
                    release_id=release_id,
                    run_id=run_id,
                    table="idiom_candidates",
                    conflict_table="idiom_conflicts",
                    stage=selected_stage,
                )
            elif selected_stage == "preprocess-graph":
                retryable, non_retryable = _plan_graph(
                    conn=conn,
                    release_id=release_id,
                    run_id=run_id,
                    config=config_obj,
                    start=start,
                    end=end,
                )
            elif selected_stage == "preprocess-continuity":
                retryable, non_retryable = _plan_continuity(
                    conn=conn,
                    release_id=release_id,
                    run_id=run_id,
                    config=config_obj,
                    start=start,
                    end=end,
                )
            elif selected_stage == "packets-build":
                retryable, non_retryable = _plan_packets(
                    conn=conn,
                    release_id=release_id,
                    run_id=run_id,
                    config=config_obj,
                    start=start,
                    end=end,
                )
            else:
                retryable, non_retryable = _plan_translation(
                    conn=conn,
                    release_id=release_id,
                    run_id=run_id,
                    config=config_obj,
                    start=start,
                    end=end,
                )
            plan.retryable.extend(retryable)
            plan.non_retryable.extend(non_retryable)
        return plan
    finally:
        conn.close()


def _rewind_summary_checkpoints(
    *,
    release_id: str,
    run_id: str,
    config: AppConfig,
    before_chapter: int,
) -> dict[str, int]:
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_schema(conn, "summaries")
    try:
        existing = get_summary_checkpoint(conn, release_id=release_id, run_id=run_id) or (0, 0, 0)
        target = max(0, before_chapter - 1)
        rewound = {
            "zh_last_chapter": min(existing[0], target),
            "story_last_chapter": min(existing[1], target),
            "en_last_chapter": min(existing[2], target),
        }
        set_summary_checkpoint(
            conn,
            release_id=release_id,
            run_id=run_id,
            zh_last_chapter=rewound["zh_last_chapter"],
            story_last_chapter=rewound["story_last_chapter"],
            en_last_chapter=rewound["en_last_chapter"],
        )
        return rewound
    finally:
        conn.close()


def execute_retry_failed(
    *,
    release_id: str,
    run_id: str,
    stage: str = "all",
    chapter: int | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    dry_run: bool = False,
    config: AppConfig | None = None,
) -> StageResult:
    config_obj = config or load_config()
    plan = plan_retry_failed(
        release_id=release_id,
        run_id=run_id,
        stage=stage,
        chapter=chapter,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        config=config_obj,
    )
    if dry_run:
        return StageResult(
            success=True,
            stage_name="retry-failed",
            message=(
                f"Retry-failed dry run: {len(plan.retryable)} retryable, "
                f"{len(plan.non_retryable)} review-required"
            ),
            metadata=plan.to_dict(),
        )

    emit_event(
        run_id,
        release_id,
        "retry-failed.started",
        "retry-failed",
        message="Retry-failed execution started",
        payload=plan.to_dict(),
    )
    results: list[dict[str, object]] = []
    success = True
    from resemantica.orchestration.runner import OrchestrationRunner

    tracking_conn = ensure_tracking_db(release_id)
    try:
        original_run_state = load_run_state(tracking_conn, run_id)
    finally:
        tracking_conn.close()

    runner = OrchestrationRunner(release_id, run_id, config=config_obj)
    try:
        for item in plan.retryable:
            if item.stage == "preprocess-summaries" and item.chapter_start is not None:
                rewind = _rewind_summary_checkpoints(
                    release_id=release_id,
                    run_id=run_id,
                    config=config_obj,
                    before_chapter=item.chapter_start,
                )
            else:
                rewind = {}
            emit_event(
                run_id,
                release_id,
                "retry-failed.stage_started",
                "retry-failed",
                message=f"Retrying {item.stage}",
                payload={**item.to_dict(), "summary_checkpoint_rewind": rewind},
            )
            result = runner.run_stage(
                item.stage,
                checkpoint={},
                chapter_start=item.chapter_start,
                chapter_end=item.chapter_end,
                allow_rewind=True,
                force=False,
            )
            results.append(
                {
                    "stage": item.stage,
                    "success": result.success,
                    "message": result.message,
                    "metadata": result.metadata,
                }
            )
            if not result.success:
                success = False
                break
    finally:
        if original_run_state is not None:
            tracking_conn = ensure_tracking_db(release_id)
            try:
                save_run_state(tracking_conn, original_run_state)
            finally:
                tracking_conn.close()

    message = "Retry-failed completed" if success else "Retry-failed stopped after failed retry"
    emit_event(
        run_id,
        release_id,
        "retry-failed.completed" if success else "retry-failed.failed",
        "retry-failed",
        severity="info" if success else "error",
        message=message,
        payload={"plan": plan.to_dict(), "results": results},
    )
    return StageResult(
        success=success,
        stage_name="retry-failed",
        message=message,
        metadata={**plan.to_dict(), "results": results},
    )
