from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.tracking.models import RunState
from resemantica.tracking.repo import ensure_tracking_db, load_run_state, save_run_state

from .events import emit_event
from .models import CALLABLE_STAGES, STAGE_ORDER, StageResult, legal_transition


@dataclass(slots=True)
class ProductionPlan:
    release_id: str
    run_id: str
    stages: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "run_id": self.run_id,
            "stages": self.stages,
        }


class OrchestrationRunner:
    def __init__(
        self,
        release_id: str,
        run_id: str,
        config: AppConfig | None = None,
    ) -> None:
        self.release_id = release_id
        self.run_id = run_id
        self.config = config or load_config()

    def plan_production(
        self,
        *,
        chapter_start: int | None = None,
        chapter_end: int | None = None,
    ) -> ProductionPlan:
        stages: list[dict[str, Any]] = []
        for stage_name in STAGE_ORDER:
            options: dict[str, Any] = {}
            if stage_name in {
                "preprocess-glossary",
                "preprocess-summaries",
                "preprocess-idioms",
                "preprocess-graph",
                "packets-build",
                "translate-range",
            }:
                options = {"chapter_start": chapter_start, "chapter_end": chapter_end}
            stages.append({"stage_name": stage_name, "options": options})
        return ProductionPlan(self.release_id, self.run_id, stages)

    def run_production(
        self,
        *,
        dry_run: bool = False,
        chapter_start: int | None = None,
        chapter_end: int | None = None,
    ) -> StageResult:
        plan = self.plan_production(chapter_start=chapter_start, chapter_end=chapter_end)
        if dry_run:
            return StageResult(
                success=True,
                stage_name="production",
                message="Production dry-run plan generated",
                metadata=plan.to_dict(),
            )

        completed: list[str] = []
        for item in plan.stages:
            stage_result = self.run_stage(
                item["stage_name"],
                **dict(item.get("options", {})),
            )
            completed.append(item["stage_name"])
            if not stage_result.success:
                return StageResult(
                    success=False,
                    stage_name="production",
                    message=f"Stage {item['stage_name']} failed: {stage_result.message}",
                    checkpoint={"completed_stages": completed},
                    metadata={"failed_stage": item["stage_name"]},
                )

        emit_event(
            self.run_id,
            self.release_id,
            "run_finalized",
            "production",
            message="Production run completed successfully",
        )
        return StageResult(
            success=True,
            stage_name="production",
            message="Production run completed successfully",
            checkpoint={"completed_stages": completed},
        )

    def run_stage(
        self,
        stage_name: str,
        *,
        checkpoint: Optional[dict[str, Any]] = None,
        chapter_number: int | None = None,
        chapter_start: int | None = None,
        chapter_end: int | None = None,
        scope: str = "run",
        dry_run: bool = False,
        force: bool = False,
    ) -> StageResult:
        if stage_name not in CALLABLE_STAGES:
            return StageResult(
                success=False,
                stage_name=stage_name,
                message=f"Unknown stage: {stage_name}",
            )

        state = self._get_run_state()
        if state is not None and not legal_transition(state.stage_name, stage_name):
            msg = f"Illegal stage transition: {state.stage_name} -> {stage_name}"
            emit_event(
                self.run_id,
                self.release_id,
                "stage.transition_denied",
                stage_name,
                severity="error",
                message=msg,
            )
            return StageResult(success=False, stage_name=stage_name, message=msg)

        active_checkpoint = checkpoint or (state.checkpoint if state else {})
        self._update_run_state(stage_name, "running", active_checkpoint)
        emit_event(
            self.run_id,
            self.release_id,
            "stage_started",
            stage_name,
            message=f"Stage {stage_name} started",
            payload={
                "chapter_number": chapter_number,
                "chapter_start": chapter_start,
                "chapter_end": chapter_end,
                "dry_run": dry_run,
            },
        )

        try:
            result = self._execute_stage(
                stage_name,
                chapter_number=chapter_number,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                scope=scope,
                dry_run=dry_run,
                force=force,
            )
        except Exception as exc:
            result = StageResult(success=False, stage_name=stage_name, message=str(exc))

        status = "completed" if result.success else "failed"
        self._update_run_state(stage_name, status, result.checkpoint or {})
        emit_event(
            self.run_id,
            self.release_id,
            "stage_completed" if result.success else "stage_failed",
            stage_name,
            severity="info" if result.success else "error",
            message=result.message,
            payload=result.metadata,
        )
        return result

    def _chapter_number_from_path(self, path: Path) -> int:
        return int(path.stem.split("-", 1)[1])

    def _resolve_chapter_range(
        self,
        *,
        chapter_start: int | None,
        chapter_end: int | None,
    ) -> tuple[int, int]:
        paths = derive_paths(self.config, release_id=self.release_id)
        chapter_files = sorted(
            paths.extracted_chapters_dir.glob("chapter-*.json"),
            key=self._chapter_number_from_path,
        )
        if not chapter_files:
            raise ValueError(
                f"No extracted chapters found for release {self.release_id}: "
                f"{paths.extracted_chapters_dir}"
            )
        chapter_numbers = [self._chapter_number_from_path(path) for path in chapter_files]
        resolved_start = chapter_start if chapter_start is not None else min(chapter_numbers)
        resolved_end = chapter_end if chapter_end is not None else max(chapter_numbers)
        if resolved_start < 1 or resolved_end < 1:
            raise ValueError("chapter_start and chapter_end must be >= 1")
        if resolved_end < resolved_start:
            raise ValueError("chapter_end must be greater than or equal to chapter_start")
        return resolved_start, resolved_end

    def _get_run_state(self) -> Optional[RunState]:
        conn = ensure_tracking_db(self.release_id)
        try:
            return load_run_state(conn, self.run_id)
        finally:
            conn.close()

    def _update_run_state(
        self,
        stage: str,
        status: str,
        checkpoint: dict[str, Any],
    ) -> RunState:
        conn = ensure_tracking_db(self.release_id)
        try:
            state = load_run_state(conn, self.run_id)
            if state is None:
                state = RunState(
                    run_id=self.run_id,
                    release_id=self.release_id,
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

    def _execute_stage(
        self,
        stage_name: str,
        *,
        chapter_number: int | None,
        chapter_start: int | None,
        chapter_end: int | None,
        scope: str,
        dry_run: bool,
        force: bool,
    ) -> StageResult:
        if stage_name == "preprocess-glossary":
            from resemantica.glossary.pipeline import (
                discover_glossary_candidates,
                promote_glossary_candidates,
                translate_glossary_candidates,
            )

            discover_glossary_candidates(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
            )
            translate_glossary_candidates(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
            )
            promote_glossary_candidates(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
            )
            return StageResult(True, stage_name, "Glossary preprocess completed")

        if stage_name == "preprocess-summaries":
            from resemantica.summaries.pipeline import preprocess_summaries

            preprocess_summaries(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
            )
            return StageResult(True, stage_name, "Summaries preprocess completed")

        if stage_name == "preprocess-idioms":
            from resemantica.idioms.pipeline import preprocess_idioms

            preprocess_idioms(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
            )
            return StageResult(True, stage_name, "Idioms preprocess completed")

        if stage_name == "preprocess-graph":
            from resemantica.graph.pipeline import preprocess_graph

            preprocess_graph(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
            )
            return StageResult(True, stage_name, "Graph preprocess completed")

        if stage_name == "packets-build":
            from resemantica.packets.builder import build_packets

            packet_result = build_packets(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_number=chapter_number,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
            )
            failed_value = packet_result.get("chapters_failed", 0)
            failed = int(failed_value) if isinstance(failed_value, (int, str)) else 0
            msg = (
                f"Packets: {packet_result.get('chapters_built', 0)} built, "
                f"{packet_result.get('chapters_up_to_date', 0)} up-to-date, "
                f"{packet_result.get('chapters_skipped', 0)} skipped, {failed} failed"
            )
            return StageResult(failed == 0, stage_name, msg, metadata=dict(packet_result))

        if stage_name == "translate-chapter":
            if chapter_number is None:
                return StageResult(False, stage_name, "translate-chapter requires chapter_number")
            return self._translate_chapter(chapter_number=chapter_number, force=force)

        if stage_name == "translate-range":
            try:
                chapter_start, chapter_end = self._resolve_chapter_range(
                    chapter_start=chapter_start,
                    chapter_end=chapter_end,
                )
            except ValueError as exc:
                return StageResult(False, stage_name, str(exc))
            return self._translate_range(chapter_start=chapter_start, chapter_end=chapter_end, force=force)

        if stage_name == "epub-rebuild":
            from resemantica.epub.rebuild import rebuild_translated_epub

            rebuild_result = rebuild_translated_epub(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
            )
            return StageResult(
                success=rebuild_result.status == "success",
                stage_name=stage_name,
                message=f"EPUB rebuilt at {rebuild_result.output_path}",
                metadata=rebuild_result.to_json_dict(),
            )

        if stage_name == "reset":
            from resemantica.orchestration.cleanup import apply_cleanup, plan_cleanup

            if dry_run:
                plan = plan_cleanup(self.release_id, self.run_id, scope=scope, dry_run=True)
                return StageResult(True, stage_name, "Cleanup plan created", metadata=plan)
            report = apply_cleanup(self.release_id, self.run_id, scope=scope, force=force)
            return StageResult(
                bool(report.get("success", True)),
                stage_name,
                report.get("message", "Cleanup applied"),
                metadata=report,
            )

        return StageResult(False, stage_name, f"Unknown stage: {stage_name}")

    def _translate_chapter(self, *, chapter_number: int, force: bool = False) -> StageResult:
        from resemantica.translation.pipeline import (
            translate_chapter_pass1,
            translate_chapter_pass2,
            translate_chapter_pass3,
        )

        emit_event(
            self.run_id,
            self.release_id,
            "chapter_started",
            "translate-chapter",
            chapter_number=chapter_number,
            message=f"Chapter {chapter_number} translation started",
        )
        pass1_result = translate_chapter_pass1(
            release_id=self.release_id,
            chapter_number=chapter_number,
            run_id=self.run_id,
            config=self.config,
            force=force,
        )
        emit_event(
            self.run_id,
            self.release_id,
            "artifact_written",
            "translate-chapter",
            chapter_number=chapter_number,
            message="Pass1 artifact written",
            payload={"artifact_path": pass1_result.get("pass1_artifact")},
        )
        pass2_result = translate_chapter_pass2(
            release_id=self.release_id,
            chapter_number=chapter_number,
            run_id=self.run_id,
            config=self.config,
            force=force,
        )
        emit_event(
            self.run_id,
            self.release_id,
            "artifact_written",
            "translate-chapter",
            chapter_number=chapter_number,
            message="Pass2 artifact written",
            payload={"artifact_path": pass2_result.get("pass2_artifact")},
        )
        pass3_result = translate_chapter_pass3(
            release_id=self.release_id,
            chapter_number=chapter_number,
            run_id=self.run_id,
            config=self.config,
        )
        if pass3_result.get("pass3_artifact"):
            emit_event(
                self.run_id,
                self.release_id,
                "artifact_written",
                "translate-chapter",
                chapter_number=chapter_number,
                message="Pass3 artifact written",
                payload={"artifact_path": pass3_result.get("pass3_artifact")},
            )
        checkpoint = {
            "chapter_number": chapter_number,
            "pass1_status": pass1_result.get("status"),
            "pass2_status": pass2_result.get("status"),
            "pass3_status": pass3_result.get("status"),
        }
        emit_event(
            self.run_id,
            self.release_id,
            "chapter_completed",
            "translate-chapter",
            chapter_number=chapter_number,
            message=f"Chapter {chapter_number} translation completed",
            payload=checkpoint,
        )
        return StageResult(
            True,
            "translate-chapter",
            f"Chapter {chapter_number} translated",
            checkpoint=checkpoint,
            metadata=checkpoint,
        )

    def _translate_range(
        self,
        *,
        chapter_start: int,
        chapter_end: int,
        force: bool = False,
    ) -> StageResult:
        completed: list[int] = []
        failures: dict[int, str] = {}
        for chapter_number in range(chapter_start, chapter_end + 1):
            result = self._translate_chapter(chapter_number=chapter_number, force=force)
            if result.success:
                completed.append(chapter_number)
                self._update_run_state(
                    "translate-range",
                    "running",
                    {"completed_chapters": completed, "failures": failures},
                )
                continue
            failures[chapter_number] = result.message
            break
        return StageResult(
            success=not failures,
            stage_name="translate-range",
            message=f"Translated {len(completed)} chapters; {len(failures)} failed",
            checkpoint={"completed_chapters": completed, "failures": failures},
            metadata={"completed_chapters": completed, "failures": failures},
        )


def run_stage(
    release_id: str,
    run_id: str,
    stage_name: str,
    *,
    checkpoint: Optional[dict[str, Any]] = None,
    chapter_number: int | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    scope: str = "run",
    dry_run: bool = False,
    force: bool = False,
) -> StageResult:
    runner = OrchestrationRunner(release_id=release_id, run_id=run_id)
    return runner.run_stage(
        stage_name,
        checkpoint=checkpoint,
        chapter_number=chapter_number,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        scope=scope,
        dry_run=dry_run,
        force=force,
    )
