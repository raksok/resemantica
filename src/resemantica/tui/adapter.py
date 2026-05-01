from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from resemantica.epub.extractor import extract_epub as _extract_epub
from resemantica.orchestration import OrchestrationRunner
from resemantica.orchestration.cleanup import apply_cleanup, plan_cleanup
from resemantica.orchestration.stop import StopToken
from resemantica.settings import load_config


@dataclass(slots=True)
class TUIAdapter:
    release_id: str
    run_id: str
    config_path: Path | None = None
    runner: OrchestrationRunner | None = None

    def _runner(self, stop_token: StopToken | None = None) -> OrchestrationRunner:
        if self.runner is not None:
            return self.runner
        return OrchestrationRunner(
            self.release_id,
            self.run_id,
            config=load_config(self.config_path),
            stop_token=stop_token,
        )

    def extract_epub(self, input_path: Path) -> Any:
        config = load_config(self.config_path)
        return _extract_epub(
            input_path=input_path,
            release_id=self.release_id,
            config=config,
            run_id=self.run_id,
        )

    def launch_stage(
        self,
        stage_name: str,
        *,
        stop_token: StopToken | None = None,
        **options: Any,
    ) -> Any:
        runner = self._runner(stop_token)
        if stop_token is None:
            return runner.run_stage(stage_name, **options)
        return runner.run_stage(stage_name, stop_token=stop_token, **options)

    def launch_production(
        self,
        *,
        stop_token: StopToken | None = None,
        **options: Any,
    ) -> Any:
        return self._runner(stop_token).run_production(**options)

    def launch_workflow(
        self,
        workflow_name: str,
        *,
        stop_token: StopToken | None = None,
        **options: Any,
    ) -> Any:
        runner = self._runner(stop_token)
        if workflow_name == "production":
            return runner.run_production(**options)
        if workflow_name == "preprocessing":
            results = []
            for stage_name in (
                "preprocess-glossary",
                "preprocess-summaries",
                "preprocess-idioms",
                "preprocess-graph",
                "packets-build",
            ):
                if stop_token is None:
                    result = runner.run_stage(stage_name, **options)
                else:
                    result = runner.run_stage(stage_name, stop_token=stop_token, **options)
                results.append(result)
                if not result.success or getattr(result, "stopped", False):
                    return result
            return results[-1] if results else None
        if workflow_name == "translation":
            if stop_token is None:
                return runner.run_stage("translate-range", **options)
            return runner.run_stage("translate-range", stop_token=stop_token, **options)
        if workflow_name == "reconstruction":
            if stop_token is None:
                return runner.run_stage("epub-rebuild", **options)
            return runner.run_stage("epub-rebuild", stop_token=stop_token, **options)
        if workflow_name == "reset":
            if stop_token is None:
                return runner.run_stage("reset", **options)
            return runner.run_stage("reset", stop_token=stop_token, **options)
        if stop_token is None:
            return runner.run_stage(workflow_name, **options)
        return runner.run_stage(workflow_name, stop_token=stop_token, **options)

    def preview_reset(self, scope: str, run_id: str | None = None) -> dict[str, Any]:
        return plan_cleanup(self.release_id, run_id or self.run_id, scope=scope, dry_run=True)

    def apply_reset(self, scope: str, run_id: str | None = None) -> dict[str, Any]:
        return apply_cleanup(self.release_id, run_id or self.run_id, scope=scope)
