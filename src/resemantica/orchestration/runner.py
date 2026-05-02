from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.llm.client import LLMClient, capture_usage_snapshot, usage_payload_delta
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.tracking.models import RunState
from resemantica.tracking.repo import ensure_tracking_db, load_run_state, save_run_state

from .events import emit_event
from .models import CALLABLE_STAGES, STAGE_ORDER, StageResult, legal_transition
from .stop import StopRequested, StopToken, raise_if_stop_requested


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
        stop_token: StopToken | None = None,
    ) -> None:
        self.release_id = release_id
        self.run_id = run_id
        self.config = config or load_config()
        self.stop_token = stop_token

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
        batched_model_order: bool | None = None,
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
            if self.stop_token is not None and self.stop_token.requested:
                checkpoint = {"completed_stages": completed}
                self._update_run_state("production", "stopped", checkpoint)
                emit_event(
                    self.run_id,
                    self.release_id,
                    "stage_stopped",
                    "production",
                    message="Production stopped before launching next stage",
                    payload={"checkpoint": checkpoint},
                )
                return StageResult(
                    success=True,
                    stage_name="production",
                    message="Production stopped before launching next stage",
                    checkpoint=checkpoint,
                    metadata={"checkpoint": checkpoint},
                    stopped=True,
                )
            stage_result = self.run_stage(
                item["stage_name"],
                **dict(item.get("options", {})),
                batched_model_order=batched_model_order,
            )
            completed.append(item["stage_name"])
            if stage_result.stopped:
                checkpoint = {"completed_stages": completed, "stopped_stage": item["stage_name"]}
                self._update_run_state("production", "stopped", checkpoint)
                return StageResult(
                    success=True,
                    stage_name="production",
                    message=f"Production stopped during {item['stage_name']}",
                    checkpoint=checkpoint,
                    metadata={"stopped_stage": item["stage_name"]},
                    stopped=True,
                )
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
        batched_model_order: bool | None = None,
        stop_token: StopToken | None = None,
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
            f"{stage_name}.started",
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
            active_stop_token = stop_token or self.stop_token
            raise_if_stop_requested(
                active_stop_token,
                checkpoint=active_checkpoint,
                message=f"Stage {stage_name} stopped before starting",
            )
            result = self._execute_stage(
                stage_name,
                chapter_number=chapter_number,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                scope=scope,
                dry_run=dry_run,
                force=force,
                batched_model_order=batched_model_order,
                stop_token=active_stop_token,
            )
        except StopRequested as exc:
            result = StageResult(
                success=True,
                stage_name=stage_name,
                message=exc.message,
                checkpoint=exc.checkpoint,
                metadata={"checkpoint": exc.checkpoint},
                stopped=True,
            )
        except Exception as exc:
            result = StageResult(success=False, stage_name=stage_name, message=str(exc))

        status = "stopped" if result.stopped else "completed" if result.success else "failed"
        self._update_run_state(stage_name, status, result.checkpoint or {})
        event_type = (
            f"{stage_name}.stopped"
            if result.stopped
            else f"{stage_name}.completed"
            if result.success
            else f"{stage_name}.failed"
        )
        emit_event(
            self.run_id,
            self.release_id,
            event_type,
            stage_name,
            severity="info" if result.success or result.stopped else "error",
            message=result.message,
            payload={
                **result.metadata,
                "checkpoint": result.checkpoint or {},
            },
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
        chapter_refs = list_extracted_chapters(paths)
        if not chapter_refs:
            raise ValueError(
                f"No extracted chapters found for release {self.release_id}: "
                f"{paths.extracted_chapters_dir}"
            )
        chapter_numbers = [ref.chapter_number for ref in chapter_refs]
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
            if status in {"completed", "failed", "stopped"}:
                state.finished_at = datetime.now(timezone.utc).isoformat()
            elif status == "running":
                state.finished_at = None
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
        batched_model_order: bool | None,
        stop_token: StopToken | None,
    ) -> StageResult:
        if stage_name == "preprocess-glossary":
            from resemantica.glossary.pipeline import (
                discover_glossary_candidates,
                promote_glossary_candidates,
                translate_glossary_candidates,
            )
            llm_client = LLMClient(
                base_url=self.config.llm.base_url,
                timeout_seconds=self.config.llm.timeout_seconds,
                max_retries=self.config.llm.max_retries,
            )

            discover_glossary_candidates(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                llm_client=llm_client,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                stop_token=stop_token,
            )
            translate_result = translate_glossary_candidates(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                llm_client=llm_client,
                stop_token=stop_token,
            )
            promote_result = promote_glossary_candidates(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                stop_token=stop_token,
                llm_usage_payload=capture_usage_snapshot(llm_client).to_payload(),
            )
            return StageResult(
                True,
                stage_name,
                "Glossary preprocess completed",
                metadata={**translate_result, **promote_result},
            )

        if stage_name == "preprocess-summaries":
            from resemantica.summaries.pipeline import preprocess_summaries

            summary_result = preprocess_summaries(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                stop_token=stop_token,
            )
            return StageResult(True, stage_name, "Summaries preprocess completed", metadata=summary_result)

        if stage_name == "preprocess-idioms":
            from resemantica.idioms.pipeline import preprocess_idioms

            idiom_result = preprocess_idioms(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                stop_token=stop_token,
            )
            return StageResult(True, stage_name, "Idioms preprocess completed", metadata=idiom_result)

        if stage_name == "preprocess-graph":
            from resemantica.graph.pipeline import preprocess_graph

            graph_result = preprocess_graph(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                stop_token=stop_token,
            )
            return StageResult(True, stage_name, "Graph preprocess completed", metadata=graph_result)

        if stage_name == "packets-build":
            from resemantica.packets.builder import build_packets

            packet_result = build_packets(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_number=chapter_number,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                stop_token=stop_token,
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
            return self._translate_chapter(
                chapter_number=chapter_number,
                force=force,
                stop_token=stop_token,
            )

        if stage_name == "translate-range":
            try:
                chapter_start, chapter_end = self._resolve_chapter_range(
                    chapter_start=chapter_start,
                    chapter_end=chapter_end,
                )
            except ValueError as exc:
                return StageResult(False, stage_name, str(exc))
            use_batched = (
                self.config.translation.batched_model_order
                if batched_model_order is None
                else batched_model_order
            )
            return self._translate_range(
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                force=force,
                batched_model_order=use_batched,
                stop_token=stop_token,
            )

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

    def _translate_chapter(
        self,
        *,
        chapter_number: int,
        force: bool = False,
        stop_token: StopToken | None = None,
        llm_client: LLMClient | None = None,
    ) -> StageResult:
        from resemantica.translation.pipeline import (
            translate_chapter_pass1,
            translate_chapter_pass2,
            translate_chapter_pass3,
        )
        shared_client = llm_client or LLMClient(
            base_url=self.config.llm.base_url,
            timeout_seconds=self.config.llm.timeout_seconds,
            max_retries=self.config.llm.max_retries,
        )
        usage_before = capture_usage_snapshot(shared_client)

        raise_if_stop_requested(
            stop_token,
            checkpoint={"chapter_number": chapter_number},
            message=f"Stopped before chapter {chapter_number}",
        )
        emit_event(
            self.run_id,
            self.release_id,
            "translate-chapter.chapter_completed",
            "translate-chapter",
            chapter_number=chapter_number,
            message=f"Chapter {chapter_number} batched translation completed",
        )
        pass1_result = translate_chapter_pass1(
            release_id=self.release_id,
            chapter_number=chapter_number,
            run_id=self.run_id,
            config=self.config,
            llm_client=shared_client,
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
        raise_if_stop_requested(
            stop_token,
            checkpoint={"chapter_number": chapter_number, "pass": "pass1", "status": pass1_result.get("status")},
            message=f"Stopped after pass1 of chapter {chapter_number}",
        )
        pass2_result = translate_chapter_pass2(
            release_id=self.release_id,
            chapter_number=chapter_number,
            run_id=self.run_id,
            config=self.config,
            llm_client=shared_client,
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
        raise_if_stop_requested(
            stop_token,
            checkpoint={"chapter_number": chapter_number, "pass": "pass2", "status": pass2_result.get("status")},
            message=f"Stopped after pass2 of chapter {chapter_number}",
        )
        pass3_result = translate_chapter_pass3(
            release_id=self.release_id,
            chapter_number=chapter_number,
            run_id=self.run_id,
            config=self.config,
            llm_client=shared_client,
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
        usage_payload = usage_payload_delta(shared_client, usage_before)
        emit_event(
            self.run_id,
            self.release_id,
            "chapter_completed",
            "translate-chapter",
            chapter_number=chapter_number,
            message=f"Chapter {chapter_number} translation completed",
            payload={**checkpoint, **usage_payload},
        )
        raise_if_stop_requested(
            stop_token,
            checkpoint=checkpoint,
            message=f"Stopped after pass3 of chapter {chapter_number}",
        )
        return StageResult(
            True,
            "translate-chapter",
            f"Chapter {chapter_number} translated",
            checkpoint=checkpoint,
            metadata={**checkpoint, **usage_payload},
        )

    def _translate_range(
        self,
        *,
        chapter_start: int,
        chapter_end: int,
        force: bool = False,
        batched_model_order: bool = False,
        stop_token: StopToken | None = None,
    ) -> StageResult:
        if batched_model_order:
            return self._translate_range_batched(
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                force=force,
                stop_token=stop_token,
            )
        client = LLMClient(
            base_url=self.config.llm.base_url,
            timeout_seconds=self.config.llm.timeout_seconds,
            max_retries=self.config.llm.max_retries,
        )
        usage_before = capture_usage_snapshot(client)
        completed: list[int] = []
        failures: dict[int, str] = {}
        for chapter_number in range(chapter_start, chapter_end + 1):
            raise_if_stop_requested(
                stop_token,
                checkpoint={"completed_chapters": completed, "failures": failures},
                message="Translation stopped before launching next chapter",
            )
            result = self._translate_chapter(
                chapter_number=chapter_number,
                force=force,
                stop_token=stop_token,
                llm_client=client,
            )
            if result.success:
                completed.append(chapter_number)
                self._update_run_state(
                    "translate-range",
                    "running",
                    {"completed_chapters": completed, "failures": failures},
                )
                raise_if_stop_requested(
                    stop_token,
                    checkpoint={"completed_chapters": completed, "failures": failures},
                    message=f"Translation stopped after chapter {chapter_number}",
                )
                continue
            failures[chapter_number] = result.message
            break
        usage_payload = usage_payload_delta(client, usage_before)
        return StageResult(
            success=not failures,
            stage_name="translate-range",
            message=f"Translated {len(completed)} chapters; {len(failures)} failed",
            checkpoint={"completed_chapters": completed, "failures": failures},
            metadata={"completed_chapters": completed, "failures": failures, **usage_payload},
        )

    def _translate_range_batched(
        self,
        *,
        chapter_start: int,
        chapter_end: int,
        force: bool = False,
        stop_token: StopToken | None = None,
    ) -> StageResult:
        from resemantica.translation.pipeline import (
            translate_chapter_pass1,
            translate_chapter_pass2,
            translate_chapter_pass3,
        )

        chapters = list(range(chapter_start, chapter_end + 1))
        pass1_completed: list[int] = []
        pass2_completed: list[int] = []
        pass3_completed: list[int] = []
        failures: dict[int, str] = {}
        client = LLMClient(
            base_url=self.config.llm.base_url,
            timeout_seconds=self.config.llm.timeout_seconds,
            max_retries=self.config.llm.max_retries,
        )
        usage_before = capture_usage_snapshot(client)
        chapter_usage_before = {
            chapter_number: capture_usage_snapshot(client)
            for chapter_number in chapters
        }

        for chapter_number in chapters:
            raise_if_stop_requested(
                stop_token,
                checkpoint={
                    "batched_model_order": True,
                    "pass1_completed": pass1_completed,
                    "pass2_completed": pass2_completed,
                    "pass3_completed": pass3_completed,
                    "failures": failures,
                },
                message="Batched translation stopped before next pass1 chapter",
            )
            emit_event(
                self.run_id,
                self.release_id,
                "translate-chapter.chapter_started",
                "translate-chapter",
                chapter_number=chapter_number,
                message=f"Chapter {chapter_number} translation started",
            )
            try:
                result = translate_chapter_pass1(
                    release_id=self.release_id,
                    chapter_number=chapter_number,
                    run_id=self.run_id,
                    config=self.config,
                    llm_client=client,
                    force=force,
                )
                pass1_completed.append(chapter_number)
                emit_event(
                    self.run_id,
                    self.release_id,
                    "translate-chapter.artifact_written",
                    "translate-chapter",
                    chapter_number=chapter_number,
                    message="Pass1 artifact written",
                    payload={"artifact_path": result.get("pass1_artifact"), "pass_name": "pass1"},
                )
            except Exception as exc:
                failures[chapter_number] = str(exc)
                break
            self._update_run_state(
                "translate-range",
                "running",
                {
                    "batched_model_order": True,
                    "pass1_completed": pass1_completed,
                    "pass2_completed": pass2_completed,
                    "pass3_completed": pass3_completed,
                    "failures": failures,
                },
            )
            raise_if_stop_requested(
                stop_token,
                checkpoint={
                    "batched_model_order": True,
                    "pass1_completed": pass1_completed,
                    "pass2_completed": pass2_completed,
                    "pass3_completed": pass3_completed,
                    "failures": failures,
                },
                message=f"Batched translation stopped after pass1 chapter {chapter_number}",
            )

        for chapter_number in pass1_completed:
            if failures:
                break
            raise_if_stop_requested(
                stop_token,
                checkpoint={
                    "batched_model_order": True,
                    "pass1_completed": pass1_completed,
                    "pass2_completed": pass2_completed,
                    "pass3_completed": pass3_completed,
                    "failures": failures,
                },
                message="Batched translation stopped before next pass2 chapter",
            )
            try:
                result = translate_chapter_pass2(
                    release_id=self.release_id,
                    chapter_number=chapter_number,
                    run_id=self.run_id,
                    config=self.config,
                    llm_client=client,
                    force=force,
                )
                pass2_completed.append(chapter_number)
                emit_event(
                    self.run_id,
                    self.release_id,
                    "translate-chapter.artifact_written",
                    "translate-chapter",
                    chapter_number=chapter_number,
                    message="Pass2 artifact written",
                    payload={"artifact_path": result.get("pass2_artifact"), "pass_name": "pass2"},
                )
            except Exception as exc:
                failures[chapter_number] = str(exc)
                break
            self._update_run_state(
                "translate-range",
                "running",
                {
                    "batched_model_order": True,
                    "pass1_completed": pass1_completed,
                    "pass2_completed": pass2_completed,
                    "pass3_completed": pass3_completed,
                    "failures": failures,
                },
            )
            raise_if_stop_requested(
                stop_token,
                checkpoint={
                    "batched_model_order": True,
                    "pass1_completed": pass1_completed,
                    "pass2_completed": pass2_completed,
                    "pass3_completed": pass3_completed,
                    "failures": failures,
                },
                message=f"Batched translation stopped after pass2 chapter {chapter_number}",
            )

        for chapter_number in pass2_completed:
            if failures:
                break
            raise_if_stop_requested(
                stop_token,
                checkpoint={
                    "batched_model_order": True,
                    "pass1_completed": pass1_completed,
                    "pass2_completed": pass2_completed,
                    "pass3_completed": pass3_completed,
                    "failures": failures,
                },
                message="Batched translation stopped before next pass3 chapter",
            )
            try:
                result = translate_chapter_pass3(
                    release_id=self.release_id,
                    chapter_number=chapter_number,
                    run_id=self.run_id,
                    config=self.config,
                    llm_client=client,
                )
                pass3_completed.append(chapter_number)
                if result.get("pass3_artifact"):
                    emit_event(
                        self.run_id,
                        self.release_id,
                        "translate-chapter.artifact_written",
                        "translate-chapter",
                        chapter_number=chapter_number,
                        message="Pass3 artifact written",
                        payload={"artifact_path": result.get("pass3_artifact"), "pass_name": "pass3"},
                    )
                emit_event(
                    self.run_id,
                    self.release_id,
                    "translate-chapter.chapter_completed",
                    "translate-chapter",
                    chapter_number=chapter_number,
                    message=f"Chapter {chapter_number} batched translation completed",
                    payload=usage_payload_delta(client, chapter_usage_before[chapter_number]),
                )
            except Exception as exc:
                failures[chapter_number] = str(exc)
                break
            self._update_run_state(
                "translate-range",
                "running",
                {
                    "batched_model_order": True,
                    "pass1_completed": pass1_completed,
                    "pass2_completed": pass2_completed,
                    "pass3_completed": pass3_completed,
                    "failures": failures,
                },
            )
            raise_if_stop_requested(
                stop_token,
                checkpoint={
                    "batched_model_order": True,
                    "pass1_completed": pass1_completed,
                    "pass2_completed": pass2_completed,
                    "pass3_completed": pass3_completed,
                    "failures": failures,
                },
                message=f"Batched translation stopped after pass3 chapter {chapter_number}",
            )

        checkpoint = {
            "batched_model_order": True,
            "pass1_completed": pass1_completed,
            "pass2_completed": pass2_completed,
            "pass3_completed": pass3_completed,
            "failures": failures,
        }
        usage_payload = usage_payload_delta(client, usage_before)
        return StageResult(
            success=not failures,
            stage_name="translate-range",
            message=(
                f"Batched translation pass1={len(pass1_completed)}, "
                f"pass2={len(pass2_completed)}, pass3={len(pass3_completed)}, "
                f"failures={len(failures)}"
            ),
            checkpoint=checkpoint,
            metadata={**checkpoint, **usage_payload},
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
    batched_model_order: bool | None = None,
    stop_token: StopToken | None = None,
) -> StageResult:
    runner = OrchestrationRunner(release_id=release_id, run_id=run_id, stop_token=stop_token)
    return runner.run_stage(
        stage_name,
        checkpoint=checkpoint,
        chapter_number=chapter_number,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        scope=scope,
        dry_run=dry_run,
        force=force,
        batched_model_order=batched_model_order,
        stop_token=stop_token,
    )
