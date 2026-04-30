from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from resemantica.orchestration import OrchestrationRunner
from resemantica.orchestration.cleanup import apply_cleanup, plan_cleanup
from resemantica.settings import load_config


@dataclass(slots=True)
class TUIAdapter:
    release_id: str
    run_id: str
    config_path: Path | None = None
    runner: OrchestrationRunner | None = None

    def _runner(self) -> OrchestrationRunner:
        if self.runner is not None:
            return self.runner
        return OrchestrationRunner(
            self.release_id,
            self.run_id,
            config=load_config(self.config_path),
        )

    def launch_workflow(self, workflow_name: str, **options: Any) -> Any:
        runner = self._runner()
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
                result = runner.run_stage(stage_name, **options)
                results.append(result)
                if not result.success:
                    return result
            return results[-1] if results else None
        if workflow_name == "translation":
            return runner.run_stage("translate-range", **options)
        if workflow_name == "reconstruction":
            return runner.run_stage("epub-rebuild", **options)
        if workflow_name == "reset":
            return runner.run_stage("reset", **options)
        return runner.run_stage(workflow_name, **options)

    def preview_reset(self, scope: str, run_id: str | None = None) -> dict[str, Any]:
        return plan_cleanup(self.release_id, run_id or self.run_id, scope=scope, dry_run=True)

    def apply_reset(self, scope: str, run_id: str | None = None) -> dict[str, Any]:
        return apply_cleanup(self.release_id, run_id or self.run_id, scope=scope)
