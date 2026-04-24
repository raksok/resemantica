from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def mock_mlflow():
    with patch("resemantica.tracking.mlflow.mlflow") as mock:
        yield mock


@pytest.fixture
def mock_load_config(tmp_path: Path) -> None:
    import resemantica.settings
    orig = resemantica.settings.load_config

    def fake_load():
        cfg = orig()
        cfg.paths.artifact_root = str(tmp_path)
        return cfg

    resemantica.settings.load_config = fake_load
    yield
    resemantica.settings.load_config = orig


def test_start_run_tracking_sets_experiment_and_run(mock_mlflow, tmp_path: Path):
    from resemantica.tracking import mlflow as _m
    _m._SUBSCRIBED = False
    _m.start_run_tracking("release-01", "run-001")

    mock_mlflow.set_tracking_uri.assert_called_once()
    mock_mlflow.set_experiment.assert_called_once_with("release-01")
    mock_mlflow.start_run.assert_called_once()
    mock_mlflow.log_param.assert_any_call("release_id", "release-01")
    mock_mlflow.log_param.assert_any_call("run_id", "run-001")


def test_start_run_tracking_subscribes_once(mock_mlflow, tmp_path: Path):
    from resemantica.tracking import mlflow as _m
    from resemantica.orchestration.events import _subscribers

    _subscribers.clear()
    _m._SUBSCRIBED = False
    _m.start_run_tracking("r1", "u1")
    assert len(_subscribers.get("stage.started", [])) == 1
    assert len(_subscribers.get("stage.completed", [])) == 1
    assert len(_subscribers.get("stage.failed", [])) == 1

    _m.start_run_tracking("r2", "u2")
    assert len(_subscribers["stage.started"]) == 1

    _m.stop_run_tracking()


def test_stop_run_tracking_ends_run(mock_mlflow):
    from resemantica.tracking.mlflow import stop_run_tracking

    stop_run_tracking()
    mock_mlflow.end_run.assert_called_once()


def test_track_run_metadata_logs_params_and_metrics(mock_mlflow):
    from resemantica.tracking.mlflow import track_run_metadata

    track_run_metadata("run-001", "release-01", {
        "model_name": "gpt-4",
        "prompt_version": "v2",
        "latency": 42.5,
        "retry_count": 3,
    })

    mock_mlflow.log_params.assert_called_once_with({
        "model_name": "gpt-4",
        "prompt_version": "v2",
    })
    mock_mlflow.log_metrics.assert_called_once_with({
        "latency": 42.5,
        "retry_count": 3.0,
    })


def test_track_run_metadata_logs_long_text_as_artifact(mock_mlflow):
    from resemantica.tracking.mlflow import track_run_metadata

    long_text = "x" * 300
    track_run_metadata("r1", "rel1", {"long_val": long_text})

    mock_mlflow.log_text.assert_called_once_with(long_text, "long_val.txt")


def test_stage_event_handler_logs_start(mock_mlflow):
    from resemantica.tracking.mlflow import _on_stage_event
    from resemantica.tracking.models import Event

    event = Event(
        event_type="stage.started",
        run_id="r1",
        release_id="rel1",
        stage_name="preprocess-glossary",
    )
    _on_stage_event(event)

    mock_mlflow.log_param.assert_called_once()
    assert "preprocess-glossary" in mock_mlflow.log_param.call_args[0][0]


def test_stage_event_handler_logs_completion(mock_mlflow):
    from resemantica.tracking.mlflow import _on_stage_event
    from resemantica.tracking.models import Event

    _on_stage_event(Event(
        event_type="stage.started",
        run_id="r1", release_id="rel1",
        stage_name="test-stage",
    ))

    import time
    time.sleep(0.01)

    _on_stage_event(Event(
        event_type="stage.completed",
        run_id="r1", release_id="rel1",
        stage_name="test-stage",
        message="done",
        payload={"items": 5},
    ))

    mock_mlflow.log_metric.assert_called()
    mock_mlflow.log_param.assert_any_call(
        "stage.test-stage.status", "completed"
    )
    mock_mlflow.log_text.assert_called()
    mock_mlflow.log_metric.assert_any_call(
        "stage.test-stage.items", 5.0
    )


def test_log_artifact_calls_mlflow(mock_mlflow):
    from resemantica.tracking.mlflow import log_artifact

    log_artifact("/tmp/test.txt", artifact_path="reports")
    mock_mlflow.log_artifact.assert_called_once_with(
        "/tmp/test.txt", artifact_path="reports"
    )
