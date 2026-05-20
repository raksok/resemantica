from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.llm.client import LLMClient, capture_usage_snapshot, usage_payload_delta
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.tracking.models import RunState
from resemantica.tracking.repo import ensure_tracking_db, load_run_state, save_run_state

from .events import emit_event
from .gates import GateReport, check_stage_gate
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
                "preprocess-continuity",
                "packets-build",
                "translate-range",
                "epub-rebuild",
            }:
                options = {"chapter_start": chapter_start, "chapter_end": chapter_end}
            gate = check_stage_gate(
                stage_name=stage_name,
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
            )
            stages.append({"stage_name": stage_name, "options": options, "gate": gate.to_dict()})
        return ProductionPlan(self.release_id, self.run_id, stages)

    def run_production(
        self,
        *,
        dry_run: bool = False,
        chapter_start: int | None = None,
        chapter_end: int | None = None,
        force: bool = False,
        batched_model_order: bool | None = None,
    ) -> StageResult:
        state = self._get_run_state()
        effective_chapter_start = chapter_start
        effective_chapter_end = chapter_end
        start_index = 0
        if state is not None and state.stage_name in STAGE_ORDER and not force:
            if effective_chapter_start is None:
                effective_chapter_start = self._checkpoint_int(state.checkpoint, "chapter_start")
            if effective_chapter_end is None:
                effective_chapter_end = self._checkpoint_int(state.checkpoint, "chapter_end")
            stage_index = STAGE_ORDER.index(state.stage_name)
            start_index = stage_index + 1 if state.status == "completed" else stage_index

        plan = self.plan_production(
            chapter_start=effective_chapter_start,
            chapter_end=effective_chapter_end,
        )
        if dry_run:
            return StageResult(
                success=True,
                stage_name="production",
                message="Production dry-run plan generated",
                metadata=plan.to_dict(),
            )

        if start_index >= len(plan.stages):
            already_complete_checkpoint: dict[str, object] = {"completed_stages": list(STAGE_ORDER)}
            return StageResult(
                success=True,
                stage_name="production",
                message="Production run already completed",
                checkpoint=already_complete_checkpoint,
                metadata={"checkpoint": already_complete_checkpoint},
            )

        completed: list[str] = list(STAGE_ORDER[:start_index])
        for item in plan.stages[start_index:]:
            if self.stop_token is not None and self.stop_token.requested:
                checkpoint: dict[str, object] = {"completed_stages": completed}
                if effective_chapter_start is not None:
                    checkpoint["chapter_start"] = effective_chapter_start
                if effective_chapter_end is not None:
                    checkpoint["chapter_end"] = effective_chapter_end
                self._update_run_state(item["stage_name"], "stopped", checkpoint)
                emit_event(
                    self.run_id,
                    self.release_id,
                    "stage_stopped",
                    item["stage_name"],
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
                force=force,
                batched_model_order=batched_model_order,
                enforce_gates=True,
            )
            if stage_result.stopped:
                checkpoint = {"completed_stages": completed, "stopped_stage": item["stage_name"]}
                return StageResult(
                    success=True,
                    stage_name="production",
                    message=f"Production stopped during {item['stage_name']}",
                    checkpoint=checkpoint,
                    metadata={"stopped_stage": item["stage_name"]},
                    stopped=True,
                )
            if not stage_result.success:
                metadata: dict[str, object] = {
                    "failed_stage": item["stage_name"],
                    "stage_result": stage_result.metadata,
                }
                for key in ("gate", "review_artifacts", "review_errors"):
                    if key in stage_result.metadata:
                        metadata[key] = stage_result.metadata[key]
                return StageResult(
                    success=False,
                    stage_name="production",
                    message=f"Stage {item['stage_name']} failed: {stage_result.message}",
                    checkpoint={"completed_stages": completed},
                    metadata=metadata,
                )
            completed.append(item["stage_name"])

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

    def _checkpoint_int(self, checkpoint: dict[str, Any], key: str) -> int | None:
        value = checkpoint.get(key)
        if isinstance(value, int):
            return value
        return None

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
        allow_rewind: bool = False,
        batched_model_order: bool | None = None,
        stop_token: StopToken | None = None,
        enforce_gates: bool = False,
    ) -> StageResult:
        if stage_name not in CALLABLE_STAGES:
            return StageResult(
                success=False,
                stage_name=stage_name,
                message=f"Unknown stage: {stage_name}",
            )

        state = self._get_run_state()
        if state is not None and not legal_transition(state.stage_name, stage_name):
            if allow_rewind:
                self._update_run_state(stage_name, "rewound", {})
            else:
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
        if enforce_gates and stage_name in STAGE_ORDER:
            gate = self._check_stage_gate(
                stage_name,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
            )
            if not gate.success:
                saved_checkpoint = dict(active_checkpoint)
                if chapter_start is not None:
                    saved_checkpoint["chapter_start"] = chapter_start
                if chapter_end is not None:
                    saved_checkpoint["chapter_end"] = chapter_end
                result_metadata: dict[str, object] = {"gate": gate.to_dict()}
                review_artifacts, review_errors = self._generate_gate_review_artifacts(gate)
                if review_artifacts:
                    result_metadata["review_artifacts"] = review_artifacts
                if review_errors:
                    result_metadata["review_errors"] = review_errors
                self._update_run_state(stage_name, "failed", saved_checkpoint)
                emit_event(
                    self.run_id,
                    self.release_id,
                    f"{stage_name}.gate_failed",
                    stage_name,
                    severity="error",
                    message=gate.message(),
                    payload={**result_metadata, "checkpoint": saved_checkpoint},
                )
                return StageResult(
                    success=False,
                    stage_name=stage_name,
                    message=gate.message(),
                    checkpoint=saved_checkpoint,
                    metadata=result_metadata,
                )
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
                checkpoint=active_checkpoint,
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
            logger.opt(exception=True).error(
                "Unexpected stage failure (stage={}, release={}, run={}, chapter={}, start={}, end={})",
                stage_name,
                self.release_id,
                self.run_id,
                chapter_number,
                chapter_start,
                chapter_end,
            )
            result = StageResult(success=False, stage_name=stage_name, message=str(exc))

        status = "stopped" if result.stopped else "completed" if result.success else "failed"
        saved_checkpoint = dict(result.checkpoint or {})
        if chapter_start is not None:
            saved_checkpoint["chapter_start"] = chapter_start
        if chapter_end is not None:
            saved_checkpoint["chapter_end"] = chapter_end
        self._update_run_state(stage_name, status, saved_checkpoint)
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

    def _check_stage_gate(
        self,
        stage_name: str,
        *,
        chapter_start: int | None,
        chapter_end: int | None,
    ) -> GateReport:
        return check_stage_gate(
            stage_name=stage_name,
            release_id=self.release_id,
            run_id=self.run_id,
            config=self.config,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
        )

    def _generate_gate_review_artifacts(self, gate: GateReport) -> tuple[dict[str, object], list[str]]:
        unresolved = gate.metadata.get("unresolved_votes")
        if not isinstance(unresolved, dict):
            return {}, []

        artifacts: dict[str, object] = {}
        errors: list[str] = []
        if int(unresolved.get("glossary", 0) or 0) > 0:
            try:
                from resemantica.glossary.pipeline import review_glossary_candidates

                result = review_glossary_candidates(
                    release_id=self.release_id,
                    run_id=self.run_id,
                    config=self.config,
                )
                artifacts["glossary"] = {
                    "entries_written": result.get("entries_written", 0),
                    "review_path": result.get("review_path"),
                    "review_json_path": result.get("review_json_path") or result.get("review_path"),
                    "review_csv_path": result.get("review_csv_path"),
                }
            except Exception as exc:
                logger.opt(exception=True).error(
                    "Failed to generate glossary review artifacts for gate failure "
                    "(release={}, run={}, stage={})",
                    self.release_id,
                    self.run_id,
                    gate.stage_name,
                )
                errors.append(f"glossary review generation failed: {exc}")
        if int(unresolved.get("idioms", 0) or 0) > 0:
            try:
                from resemantica.idioms.pipeline import review_idiom_candidates

                result = review_idiom_candidates(
                    release_id=self.release_id,
                    run_id=self.run_id,
                    config=self.config,
                )
                artifacts["idioms"] = {
                    "entries_written": result.get("entries_written", 0),
                    "review_path": result.get("review_path"),
                    "review_json_path": result.get("review_json_path") or result.get("review_path"),
                    "review_csv_path": result.get("review_csv_path"),
                }
            except Exception as exc:
                logger.opt(exception=True).error(
                    "Failed to generate idiom review artifacts for gate failure "
                    "(release={}, run={}, stage={})",
                    self.release_id,
                    self.run_id,
                    gate.stage_name,
                )
                errors.append(f"idiom review generation failed: {exc}")
        return artifacts, errors

    def _execute_stage(
        self,
        stage_name: str,
        *,
        checkpoint: dict[str, Any] | None = None,
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
                max_concurrent_requests_per_model=self.config.llm.max_concurrent_requests_per_model,
            )

            discover_glossary_candidates(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                llm_client=llm_client,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                resume=not force,
                force=force,
                stop_token=stop_token,
            )
            translate_result = translate_glossary_candidates(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                llm_client=llm_client,
                force=force,
                stop_token=stop_token,
            )
            promote_result = promote_glossary_candidates(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                force=force,
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
                resume=not force,
                force=force,
                stop_token=stop_token,
            )
            summary_success = summary_result.get("status") == "success"
            message = (
                "Summaries preprocess completed"
                if summary_success
                else "Summaries preprocess failed"
            )
            checkpoint = summary_result.get("checkpoint")
            checkpoint_dict: dict[str, object] = (
                dict(checkpoint) if isinstance(checkpoint, dict) else {}
            )
            return StageResult(
                summary_success,
                stage_name,
                message,
                checkpoint=checkpoint_dict,
                metadata=summary_result,
            )

        if stage_name == "preprocess-idioms":
            from resemantica.idioms.pipeline import preprocess_idioms

            idiom_result = preprocess_idioms(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                resume=not force,
                force=force,
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
                resume=not force,
                force=force,
                stop_token=stop_token,
            )
            return StageResult(True, stage_name, "Graph preprocess completed", metadata=graph_result)

        if stage_name == "preprocess-continuity":
            from resemantica.summaries.continuity import preprocess_continuity

            continuity_result = preprocess_continuity(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                force=force,
                stop_token=stop_token,
            )
            return StageResult(
                True,
                stage_name,
                "Graph-grounded continuity refresh completed",
                metadata=continuity_result,
            )

        if stage_name == "packets-build":
            from resemantica.packets.builder import build_packets

            translator_budget = self.config.models.effective_max_context_per_pass(
                "translator", self.config.budget.max_context_per_pass, self.config.llm.context_window
            )
            packet_result = build_packets(
                release_id=self.release_id,
                run_id=self.run_id,
                config=self.config,
                chapter_number=chapter_number,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                stop_token=stop_token,
                budget_tokens=translator_budget,
                force_rebuild=force,
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
                checkpoint=checkpoint,
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
                chapter_start=chapter_start,
                chapter_end=chapter_end,
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
                str(report.get("message", "Cleanup applied")),
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
            max_concurrent_requests_per_model=self.config.llm.max_concurrent_requests_per_model,
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
            "translate-chapter.chapter_started",
            "translate-chapter",
            chapter_number=chapter_number,
            message=f"Chapter {chapter_number} translation started",
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
            force=force,
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
        checkpoint: dict[str, Any] | None = None,
        chapter_start: int,
        chapter_end: int,
        force: bool = False,
        batched_model_order: bool = False,
        stop_token: StopToken | None = None,
    ) -> StageResult:
        if batched_model_order:
            return self._translate_range_batched(
                checkpoint=checkpoint,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                force=force,
                stop_token=stop_token,
            )
        client = LLMClient(
            base_url=self.config.llm.base_url,
            timeout_seconds=self.config.llm.timeout_seconds,
            max_retries=self.config.llm.max_retries,
            max_concurrent_requests_per_model=self.config.llm.max_concurrent_requests_per_model,
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
        checkpoint: dict[str, Any] | None = None,
        chapter_start: int,
        chapter_end: int,
        force: bool = False,
        stop_token: StopToken | None = None,
    ) -> StageResult:
        from resemantica.db.sqlite import open_connection
        from resemantica.orchestration.chunk_checkpoints import (
            last_completed_chunk,
            load_chunk_checkpoint,
            save_chunk_checkpoint,
        )
        from resemantica.settings import derive_paths
        from resemantica.translation.pipeline import (
            translate_chapter_pass1,
            translate_chapter_pass2,
            translate_chapter_pass3,
        )

        chapters = list(range(chapter_start, chapter_end + 1))
        pass1_completed: list[int] = list(checkpoint.get("pass1_completed", [])) if checkpoint and not force else []
        pass2_completed: list[int] = list(checkpoint.get("pass2_completed", [])) if checkpoint and not force else []
        pass3_completed: list[int] = list(checkpoint.get("pass3_completed", [])) if checkpoint and not force else []
        failures: dict[int, str] = {}
        chunk_size = self.config.batch_order.translation_chunk_size
        chunked = self.config.batch_order.enabled and len(chapters) > chunk_size
        chunks = [
            chapters[index:index + chunk_size]
            for index in range(0, len(chapters), chunk_size)
        ] if chunked else [chapters]
        completed_chunk_index = -1
        paths = derive_paths(self.config, release_id=self.release_id)

        if chunked and checkpoint and not force:
            completed_chunk_index = int(checkpoint.get("completed_chunk_index", -1))
        if chunked and not force:
            conn = open_connection(paths.db_path)
            try:
                completed = last_completed_chunk(
                    conn,
                    release_id=self.release_id,
                    run_id=self.run_id,
                    stage_name="translate-range",
                )
                if completed is not None:
                    completed_chunk_index = max(completed_chunk_index, completed.chunk_index)
            finally:
                conn.close()

        client = LLMClient(
            base_url=self.config.llm.base_url,
            timeout_seconds=self.config.llm.timeout_seconds,
            max_retries=self.config.llm.max_retries,
            max_concurrent_requests_per_model=self.config.llm.max_concurrent_requests_per_model,
        )
        usage_before = capture_usage_snapshot(client)
        chapter_usage_before = {
            chapter_number: capture_usage_snapshot(client)
            for chapter_number in chapters
        }

        def checkpoint_payload() -> dict[str, object]:
            payload: dict[str, object] = {
                    "batched_model_order": True,
                    "chunked": chunked,
                    "chunk_size": chunk_size if chunked else None,
                    "completed_chunk_index": completed_chunk_index,
                    "pass1_completed": pass1_completed,
                    "pass2_completed": pass2_completed,
                    "pass3_completed": pass3_completed,
                    "failures": failures,
            }
            return payload

        def chunk_payload(chunk_index: int, chunk: list[int]) -> dict[str, object]:
            return {
                "chunk_index": chunk_index,
                "chunk_count": len(chunks),
                "chapter_start": chunk[0],
                "chapter_end": chunk[-1],
                "chunk_size": chunk_size,
                "last_good_chapter": max(pass3_completed, default=chapter_start - 1),
            }

        for chunk_index, chunk in enumerate(chunks):
            if chunked and not force:
                conn = open_connection(paths.db_path)
                try:
                    chunk_checkpoint = load_chunk_checkpoint(
                        conn,
                        release_id=self.release_id,
                        run_id=self.run_id,
                        stage_name="translate-range",
                        chunk_index=chunk_index,
                    )
                finally:
                    conn.close()
                if chunk_checkpoint is not None and chunk_checkpoint.status == "completed":
                    continue

            if chunked:
                started_payload = chunk_payload(chunk_index, chunk)
                emit_event(
                    self.run_id,
                    self.release_id,
                    "translate-range.chunk_started",
                    "translate-range",
                    message=f"Translation chunk {chunk_index + 1}/{len(chunks)} started",
                    payload=started_payload,
                )
                conn = open_connection(paths.db_path)
                try:
                    save_chunk_checkpoint(
                        conn,
                        release_id=self.release_id,
                        run_id=self.run_id,
                        stage_name="translate-range",
                        chunk_index=chunk_index,
                        chapter_start=chunk[0],
                        chapter_end=chunk[-1],
                        status="running",
                        metadata=started_payload,
                    )
                finally:
                    conn.close()

            try:
                for chapter_number in chunk:
                    if chapter_number in pass1_completed:
                        continue
                    raise_if_stop_requested(
                        stop_token,
                        checkpoint=checkpoint_payload(),
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
                        if chapter_number in failures:
                            del failures[chapter_number]
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
                        logger.opt(exception=True).error(
                            "Batched pass1 failed (release={}, run={}, chapter={})",
                            self.release_id,
                            self.run_id,
                            chapter_number,
                        )
                        emit_event(
                            self.run_id,
                            self.release_id,
                            "translate-chapter.pass1.failed",
                            "translate-chapter",
                            chapter_number=chapter_number,
                            severity="error",
                            message=f"Pass1 failed for chapter {chapter_number}: {exc}",
                            payload={"pass_name": "pass1", "reason": str(exc)},
                        )
                        failures[chapter_number] = str(exc)
                        break
                    self._update_run_state("translate-range", "running", checkpoint_payload())
                    raise_if_stop_requested(
                        stop_token,
                        checkpoint=checkpoint_payload(),
                        message=f"Batched translation stopped after pass1 chapter {chapter_number}",
                    )

                for chapter_number in [number for number in pass1_completed if number in chunk]:
                    if chapter_number in pass2_completed:
                        continue
                    if failures:
                        break
                    raise_if_stop_requested(
                        stop_token,
                        checkpoint=checkpoint_payload(),
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
                        logger.opt(exception=True).error(
                            "Batched pass2 failed (release={}, run={}, chapter={})",
                            self.release_id,
                            self.run_id,
                            chapter_number,
                        )
                        emit_event(
                            self.run_id,
                            self.release_id,
                            "translate-chapter.pass2.failed",
                            "translate-chapter",
                            chapter_number=chapter_number,
                            severity="error",
                            message=f"Pass2 failed for chapter {chapter_number}: {exc}",
                            payload={"pass_name": "pass2", "reason": str(exc)},
                        )
                        failures[chapter_number] = str(exc)
                        break
                    self._update_run_state("translate-range", "running", checkpoint_payload())
                    raise_if_stop_requested(
                        stop_token,
                        checkpoint=checkpoint_payload(),
                        message=f"Batched translation stopped after pass2 chapter {chapter_number}",
                    )

                for chapter_number in [number for number in pass2_completed if number in chunk]:
                    if chapter_number in pass3_completed:
                        continue
                    if failures:
                        break
                    raise_if_stop_requested(
                        stop_token,
                        checkpoint=checkpoint_payload(),
                        message="Batched translation stopped before next pass3 chapter",
                    )
                    try:
                        result = translate_chapter_pass3(
                            release_id=self.release_id,
                            chapter_number=chapter_number,
                            run_id=self.run_id,
                            config=self.config,
                            llm_client=client,
                            force=force,
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
                        logger.opt(exception=True).error(
                            "Batched pass3 failed (release={}, run={}, chapter={})",
                            self.release_id,
                            self.run_id,
                            chapter_number,
                        )
                        emit_event(
                            self.run_id,
                            self.release_id,
                            "translate-chapter.pass3.failed",
                            "translate-chapter",
                            chapter_number=chapter_number,
                            severity="error",
                            message=f"Pass3 failed for chapter {chapter_number}: {exc}",
                            payload={"pass_name": "pass3", "reason": str(exc)},
                        )
                        failures[chapter_number] = str(exc)
                        break
                    self._update_run_state("translate-range", "running", checkpoint_payload())
                    raise_if_stop_requested(
                        stop_token,
                        checkpoint=checkpoint_payload(),
                        message=f"Batched translation stopped after pass3 chapter {chapter_number}",
                    )

                if failures:
                    if chunked:
                        failed_payload = chunk_payload(chunk_index, chunk)
                        emit_event(
                            self.run_id,
                            self.release_id,
                            "translate-range.chunk_failed",
                            "translate-range",
                            severity="error",
                            message=f"Translation chunk {chunk_index + 1}/{len(chunks)} failed",
                            payload={**failed_payload, "failures": failures},
                        )
                        conn = open_connection(paths.db_path)
                        try:
                            save_chunk_checkpoint(
                                conn,
                                release_id=self.release_id,
                                run_id=self.run_id,
                                stage_name="translate-range",
                                chunk_index=chunk_index,
                                chapter_start=chunk[0],
                                chapter_end=chunk[-1],
                                status="failed",
                                metadata={**failed_payload, "failures": failures},
                            )
                        finally:
                            conn.close()
                    break

                if chunked:
                    completed_chunk_index = chunk_index
                    completed_payload = chunk_payload(chunk_index, chunk)
                    emit_event(
                        self.run_id,
                        self.release_id,
                        "translate-range.chunk_completed",
                        "translate-range",
                        message=f"Translation chunk {chunk_index + 1}/{len(chunks)} completed",
                        payload=completed_payload,
                    )
                    conn = open_connection(paths.db_path)
                    try:
                        save_chunk_checkpoint(
                            conn,
                            release_id=self.release_id,
                            run_id=self.run_id,
                            stage_name="translate-range",
                            chunk_index=chunk_index,
                            chapter_start=chunk[0],
                            chapter_end=chunk[-1],
                            status="completed",
                            metadata=completed_payload,
                        )
                    finally:
                        conn.close()
            except Exception as exc:
                if chunked:
                    failed_payload = chunk_payload(chunk_index, chunk)
                    emit_event(
                        self.run_id,
                        self.release_id,
                        "translate-range.chunk_failed",
                        "translate-range",
                        severity="error",
                        message=f"Translation chunk {chunk_index + 1}/{len(chunks)} failed: {exc}",
                        payload={**failed_payload, "reason": str(exc)},
                    )
                    conn = open_connection(paths.db_path)
                    try:
                        save_chunk_checkpoint(
                            conn,
                            release_id=self.release_id,
                            run_id=self.run_id,
                            stage_name="translate-range",
                            chunk_index=chunk_index,
                            chapter_start=chunk[0],
                            chapter_end=chunk[-1],
                            status="failed",
                            metadata={**failed_payload, "reason": str(exc)},
                        )
                    finally:
                        conn.close()
                raise

        checkpoint_result = checkpoint_payload()
        checkpoint_result["failures"] = failures
        usage_payload = usage_payload_delta(client, usage_before)
        return StageResult(
            success=not failures,
            stage_name="translate-range",
            message=(
                f"Batched translation pass1={len(pass1_completed)}, "
                f"pass2={len(pass2_completed)}, pass3={len(pass3_completed)}, "
                f"failures={len(failures)}"
            ),
            checkpoint=checkpoint_result,
            metadata={**checkpoint_result, **usage_payload},
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
    allow_rewind: bool = False,
    batched_model_order: bool | None = None,
    stop_token: StopToken | None = None,
    enforce_gates: bool = False,
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
        allow_rewind=allow_rewind,
        batched_model_order=batched_model_order,
        stop_token=stop_token,
        enforce_gates=enforce_gates,
    )
