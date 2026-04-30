from __future__ import annotations

from typing import Any, Optional

from resemantica.tracking.models import RunState
from resemantica.tracking.repo import ensure_tracking_db, save_run_state, load_run_state
from .models import StageResult, legal_transition, STAGE_ORDER
from .events import emit_event


def _get_run_state(release_id: str, run_id: str) -> Optional[RunState]:
    conn = ensure_tracking_db(release_id)
    try:
        return load_run_state(conn, run_id)
    finally:
        conn.close()


def _update_run_state(
    release_id: str, run_id: str, stage: str, status: str, checkpoint: dict[str, Any]
) -> RunState:
    conn = ensure_tracking_db(release_id)
    try:
        state = load_run_state(conn, run_id)
        if state is None:
            state = RunState(
                run_id=run_id,
                release_id=release_id,
                stage_name=stage,
                status=status,
                checkpoint=checkpoint,
            )
        else:
            state.stage_name = stage
            state.status = status
            state.checkpoint = checkpoint
        save_run_state(conn, state)
        return state
    finally:
        conn.close()


def run_stage(
    release_id: str,
    run_id: str,
    stage_name: str,
    *,
    checkpoint: Optional[dict[str, Any]] = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
) -> StageResult:
    state = _get_run_state(release_id, run_id)

    if state is not None and not legal_transition(state.stage_name, stage_name):
        msg = f"Illegal stage transition: {state.stage_name} -> {stage_name}"
        emit_event(
            run_id, release_id, "stage.transition_denied",
            stage_name, severity="error", message=msg
        )
        return StageResult(success=False, stage_name=stage_name, message=msg)

    _update_run_state(
        release_id, run_id, stage_name, "running",
        checkpoint or (state.checkpoint if state else {})
    )

    emit_event(
        run_id, release_id, "stage.started",
        stage_name, message=f"Stage {stage_name} started"
    )

    try:
        result = _execute_stage(release_id, run_id, stage_name, chapter_start=chapter_start, chapter_end=chapter_end)

        status = "completed" if result.success else "failed"
        _update_run_state(
            release_id, run_id, stage_name, status,
            result.checkpoint or {}
        )

        emit_event(
            run_id, release_id,
            "stage.completed" if result.success else "stage.failed",
            stage_name,
            severity="info" if result.success else "error",
            message=result.message,
            payload=result.metadata,
        )
        return result

    except Exception as exc:
        _update_run_state(release_id, run_id, stage_name, "failed", {})
        emit_event(
            run_id, release_id, "stage.error",
            stage_name, severity="error",
            message=str(exc)
        )
        return StageResult(
            success=False, stage_name=stage_name, message=str(exc)
        )


def _execute_stage(release_id: str, run_id: str, stage_name: str, *, chapter_start: int | None = None, chapter_end: int | None = None) -> StageResult:
    """Execute a stage by calling the appropriate pipeline function."""
    config = None
    try:
        from resemantica.settings import load_config
        config = load_config()
    except Exception:
        pass

    try:
        if stage_name not in STAGE_ORDER:
            return StageResult(
                success=False, stage_name=stage_name,
                message=f"Unknown stage: {stage_name}"
            )

        if stage_name == "preprocess-glossary":
            from resemantica.glossary.pipeline import (
                discover_glossary_candidates,
                translate_glossary_candidates,
                promote_glossary_candidates,
            )
            discover_glossary_candidates(release_id=release_id, run_id=run_id, config=config, chapter_start=chapter_start, chapter_end=chapter_end)
            translate_glossary_candidates(release_id=release_id, run_id=run_id, config=config)
            promote_glossary_candidates(release_id=release_id, run_id=run_id, config=config)
            return StageResult(
                success=True, stage_name=stage_name,
                message="Glossary preprocess completed"
            )

        elif stage_name == "preprocess-summaries":
            from resemantica.summaries.pipeline import preprocess_summaries
            preprocess_summaries(release_id=release_id, run_id=run_id, config=config, chapter_start=chapter_start, chapter_end=chapter_end)
            return StageResult(
                success=True, stage_name=stage_name,
                message="Summaries preprocess completed"
            )

        elif stage_name == "preprocess-idioms":
            from resemantica.idioms.pipeline import preprocess_idioms
            preprocess_idioms(release_id=release_id, run_id=run_id, config=config, chapter_start=chapter_start, chapter_end=chapter_end)
            return StageResult(
                success=True, stage_name=stage_name,
                message="Idioms preprocess completed"
            )

        elif stage_name == "preprocess-graph":
            from resemantica.graph.pipeline import preprocess_graph
            preprocess_graph(release_id=release_id, run_id=run_id, config=config, chapter_start=chapter_start, chapter_end=chapter_end)
            return StageResult(
                success=True, stage_name=stage_name,
                message="Graph preprocess completed"
            )

        elif stage_name == "packets-build":
            from resemantica.packets.builder import build_packets
            result = build_packets(
                release_id=release_id, run_id=run_id, config=config,
                chapter_start=chapter_start, chapter_end=chapter_end,
            )
            built = result.get("chapters_built", 0)
            up_to_date = result.get("chapters_up_to_date", 0)
            skipped = result.get("chapters_skipped", 0)
            failed = result.get("chapters_failed", 0)
            msg = f"Packets: {built} built, {up_to_date} up-to-date, {skipped} skipped, {failed} failed"
            return StageResult(
                success=failed == 0, stage_name=stage_name,
                message=msg,
            )

        elif stage_name == "translate-chapter":
            return StageResult(
                success=False, stage_name=stage_name,
                message="translate-chapter requires chapter_number - use translate_chapter() directly"
            )

        elif stage_name == "translate-pass3":
            return StageResult(
                success=False, stage_name=stage_name,
                message="translate-pass3 requires additional context - use translate_pass3() directly"
            )

        elif stage_name == "epub-rebuild":
            from resemantica.epub.rebuild import rebuild_epub
            from resemantica.settings import derive_paths
            if config is None:
                return StageResult(success=False, stage_name=stage_name, message="Failed to load config")
            paths = derive_paths(config, release_id=release_id)
            output_path = rebuild_epub(paths.unpacked_dir, paths.rebuilt_epub_path)
            return StageResult(
                success=True, stage_name=stage_name,
                message=f"EPUB rebuilt at {output_path}",
                metadata={"output_path": str(output_path)},
            )

        else:
            return StageResult(
                success=False, stage_name=stage_name,
                message=f"Unknown stage: {stage_name}"
            )

    except Exception as exc:
        return StageResult(
            success=False, stage_name=stage_name, message=str(exc)
        )
