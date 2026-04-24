from __future__ import annotations

import time
from typing import Any, Optional

import mlflow

from resemantica.tracking.models import Event
from resemantica.orchestration.events import subscribe

_STAGE_START_TIMES: dict[str, float] = {}
_SUBSCRIBED: bool = False


def _get_tracking_uri() -> str:
    from resemantica.settings import load_config
    cfg = load_config()
    return f"sqlite:///{cfg.paths.artifact_root}/mlflow.db"


def _on_stage_event(event: Event) -> None:
    if event.event_type == "stage.started":
        _STAGE_START_TIMES[event.stage_name] = time.time()
        mlflow.log_param(f"stage.{event.stage_name}.started", event.event_time)
        return

    if event.event_type in ("stage.completed", "stage.failed"):
        start = _STAGE_START_TIMES.pop(event.stage_name, None)
        if start is not None:
            mlflow.log_metric(
                f"stage.{event.stage_name}.latency_seconds",
                round(time.time() - start, 2),
            )
        status = "completed" if event.event_type == "stage.completed" else "failed"
        mlflow.log_param(f"stage.{event.stage_name}.status", status)
        if event.message:
            mlflow.log_text(event.message, f"stage.{event.stage_name}.message.txt")

        payload = event.payload or {}
        for k, v in payload.items():
            if isinstance(v, (int, float)):
                mlflow.log_metric(f"stage.{event.stage_name}.{k}", float(v))
            elif isinstance(v, str):
                mlflow.log_param(f"stage.{event.stage_name}.{k}", v)


def start_run_tracking(release_id: str, run_id: str) -> None:
    global _SUBSCRIBED
    mlflow.set_tracking_uri(_get_tracking_uri())
    mlflow.set_experiment(release_id)
    mlflow.start_run(run_name=run_id, run_id=run_id)
    mlflow.log_param("release_id", release_id)
    mlflow.log_param("run_id", run_id)

    if not _SUBSCRIBED:
        subscribe("stage.started", _on_stage_event)
        subscribe("stage.completed", _on_stage_event)
        subscribe("stage.failed", _on_stage_event)
        _SUBSCRIBED = True


def stop_run_tracking() -> None:
    try:
        mlflow.end_run()
    except Exception:
        pass


def track_run_metadata(
    run_id: str,
    release_id: str,
    metadata: dict[str, Any],
) -> None:
    mlflow.set_tracking_uri(_get_tracking_uri())
    mlflow.set_experiment(release_id)

    active_run = mlflow.active_run()
    if active_run is None or active_run.info.run_id != run_id:
        mlflow.start_run(run_name=run_id, run_id=run_id)

    params = {k: v for k, v in metadata.items() if isinstance(v, str) and len(v) < 250}
    metrics = {k: float(v) for k, v in metadata.items() if isinstance(v, (int, float))}

    if params:
        mlflow.log_params(params)
    if metrics:
        mlflow.log_metrics(metrics)

    for k, v in metadata.items():
        if isinstance(v, str) and len(v) >= 250:
            mlflow.log_text(v, f"{k}.txt")


def log_artifact(local_path: str, artifact_path: Optional[str] = None) -> None:
    mlflow.log_artifact(local_path, artifact_path=artifact_path)
