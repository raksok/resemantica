from __future__ import annotations

from pathlib import Path

import pytest

from resemantica.tracking.models import Event
from resemantica.tracking.repo import ensure_tracking_db, save_event
from resemantica.tracking.quality import get_stage_summary, get_warning_trends, get_metric_totals


@pytest.fixture(autouse=True)
def _tmp_artifact_root(tmp_path: Path) -> None:
    import resemantica.settings
    orig = resemantica.settings.load_config

    def fake_load():
        cfg = orig()
        cfg.paths.artifact_root = str(tmp_path)
        return cfg

    resemantica.settings.load_config = fake_load
    yield
    resemantica.settings.load_config = orig


def _seed_events(release_id: str) -> None:
    conn = ensure_tracking_db(release_id)
    try:
        for i in range(3):
            save_event(conn, Event(
                event_type="stage.completed",
                run_id="r1",
                release_id=release_id,
                stage_name="preprocess-glossary",
                severity="info",
                message=f"glossary ok {i}",
            ))
        save_event(conn, Event(
            event_type="stage.failed",
            run_id="r1",
            release_id=release_id,
            stage_name="packets-build",
            severity="error",
            message="build failed",
        ))
        save_event(conn, Event(
            event_type="stage.error",
            run_id="r1",
            release_id=release_id,
            stage_name="translate-chapter",
            severity="error",
            message="timeout",
        ))
        save_event(conn, Event(
            event_type="warning.event",
            run_id="r1",
            release_id=release_id,
            stage_name="preprocess-glossary",
            severity="warning",
            message="glossary conflict detected",
        ))
    finally:
        conn.close()


class TestGetStageSummary:
    def test_returns_stage_counts(self):
        _seed_events("test-summary-rel")
        summary = get_stage_summary("test-summary-rel")
        stages = {s["stage"]: s for s in summary}

        assert "preprocess-glossary" in stages
        assert stages["preprocess-glossary"]["completed"] == 3

        assert "packets-build" in stages
        assert stages["packets-build"]["failed"] == 1

        assert "translate-chapter" in stages
        assert stages["translate-chapter"]["errors"] == 1


class TestGetWarningTrends:
    def test_returns_warnings_and_errors(self):
        _seed_events("test-warning-rel")
        trends = get_warning_trends("test-warning-rel", limit=10)
        severities = [t["severity"] for t in trends]
        assert "warning" in severities
        assert "error" in severities

    def test_respects_limit(self):
        _seed_events("test-limit-rel")
        trends = get_warning_trends("test-limit-rel", limit=2)
        assert len(trends) <= 2


class TestGetMetricTotals:
    def test_returns_counts(self):
        _seed_events("test-metrics-rel")
        totals = get_metric_totals("test-metrics-rel")
        assert totals["total_events"] >= 6
        assert totals["warnings"] >= 1
        assert totals["errors"] >= 2
        assert totals["stages_run"] >= 3
