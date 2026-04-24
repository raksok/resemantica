from __future__ import annotations

from typing import Any


def test_event_bus_subscribe_unsubscribe():
    from resemantica.orchestration.events import subscribe, unsubscribe, emit_event

    received: list[dict[str, Any]] = []

    def callback(event):
        received.append({"type": event.event_type, "msg": event.message})

    subscribe("test.event", callback)
    try:
        import uuid
        release_id = f"test-rel-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        emit_event(
            run_id, release_id, "test.event",
            "test-stage", message="hello from bus"
        )

        assert len(received) == 1
        assert received[0]["type"] == "test.event"
        assert received[0]["msg"] == "hello from bus"

        received.clear()
        unsubscribe("test.event", callback)

        emit_event(
            run_id, release_id, "test.event",
            "test-stage", message="should not arrive"
        )

        assert len(received) == 0
    finally:
        try:
            unsubscribe("test.event", callback)
        except ValueError:
            pass


def test_event_bus_filters_by_type():
    from resemantica.orchestration.events import subscribe, unsubscribe, emit_event

    received: list[str] = []

    def cb(event):
        received.append(event.event_type)

    subscribe("type.a", cb)
    try:
        import uuid
        release_id = f"test-rel-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        emit_event(run_id, release_id, "type.a", "s")
        emit_event(run_id, release_id, "type.b", "s")
        emit_event(run_id, release_id, "type.a", "s")

        assert received == ["type.a", "type.a"]
    finally:
        try:
            unsubscribe("type.a", cb)
        except ValueError:
            pass


def test_dashboard_presenter_builds_phase_progress():
    from resemantica.tui.screens.dashboard import DashboardScreen
    screen = DashboardScreen()
    state: dict[str, Any] = {
        "run_id": "test-run",
        "release_id": "test-release",
        "stage_name": "translate-chapter",
        "status": "running",
        "started_at": "2026-04-24T12:00:00",
        "finished_at": None,
        "checkpoint": {},
        "metadata": {},
    }
    result = screen._build_phase_progress(state)
    assert "preprocess-glossary" in result
    assert "translate-chapter" in result
    assert "epub-rebuild" in result
    assert "[green]■[/] preprocess-glossary" in result  # completed
    assert "[cyan]▸[/] translate-chapter" in result  # current
    assert "[comment]□[/] epub-rebuild" in result  # not started


def test_dashboard_presenter_empty_state():
    from resemantica.tui.screens.dashboard import DashboardScreen
    screen = DashboardScreen()
    result = screen._build_phase_progress(None)
    assert "Phase Progress" in result
    assert "preprocess-glossary" in result


def test_settings_presenter_builds_config():
    from resemantica.tui.screens.settings import SettingsScreen
    screen = SettingsScreen()
    result = screen._build_config_text()
    assert "Models" in result
    assert "LLM" in result
    assert "Paths" in result
    assert "Budget" in result
    assert "Translation" in result


def test_preprocessing_presenter_builds_stages():
    from resemantica.tui.screens.preprocessing import PreprocessingScreen
    screen = PreprocessingScreen()
    state: dict[str, object] = {
        "run_id": "test-run",
        "release_id": "test-release",
        "stage_name": "preprocess-glossary",
        "status": "running",
    }
    result = screen._build_stage_progress(state)
    assert "EPUB Extract" in result
    assert "Glossary" in result
    assert "Summaries" in result
    assert "Idioms" in result
    assert "Graph MVP" in result
    assert "Packets" in result
