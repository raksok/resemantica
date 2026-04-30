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


def test_event_bus_deduplicates_subscribers():
    from resemantica.orchestration.events import subscribe, unsubscribe, emit_event

    received: list[str] = []

    def cb(event):
        received.append(event.event_type)

    subscribe("dedupe.event", cb)
    subscribe("dedupe.event", cb)
    try:
        import uuid
        release_id = f"test-rel-{uuid.uuid4().hex[:8]}"
        run_id = f"test-run-{uuid.uuid4().hex[:8]}"

        emit_event(run_id, release_id, "dedupe.event", "s")

        assert received == ["dedupe.event"]
    finally:
        unsubscribe("dedupe.event", cb)


def test_tui_adapter_launch_workflow_delegates_to_runner():
    from resemantica.tui.adapter import TUIAdapter

    class Runner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def run_stage(self, stage_name: str, **options):
            self.calls.append((stage_name, options))
            return {"stage": stage_name, "options": options}

        def run_production(self, **options):
            self.calls.append(("production", options))
            return {"stage": "production", "options": options}

    runner = Runner()
    adapter = TUIAdapter("rel", "run", runner=runner)  # type: ignore[arg-type]

    result = adapter.launch_workflow("translation", chapter_start=1, chapter_end=2)

    assert result["stage"] == "translate-range"
    assert runner.calls == [("translate-range", {"chapter_start": 1, "chapter_end": 2})]


def test_reset_preview_screen_renders_delete_and_preserve_targets():
    from resemantica.tui.screens.reset_preview import ResetPreviewScreen

    screen = ResetPreviewScreen()
    rendered = screen._render_plan(
        {
            "deletable_artifacts": ["/tmp/delete-me"],
            "preserved_artifacts": ["/tmp/keep-me"],
        }
    )

    assert "WILL DELETE" in rendered
    assert "/tmp/delete-me" in rendered
    assert "WILL PRESERVE" in rendered
    assert "/tmp/keep-me" in rendered


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


def test_preprocessing_launch_workflow_chains_stages():
    from resemantica.tui.adapter import TUIAdapter

    class Runner:
        def __init__(self) -> None:
            self.calls: list[str] = []

        class _Result:
            success = True

        def run_stage(self, stage_name: str, **options):
            self.calls.append(stage_name)
            return self._Result()

        def run_production(self, **options):
            self.calls.append("production")
            return None

    runner = Runner()
    adapter = TUIAdapter("rel", "run", runner=runner)  # type: ignore[arg-type]
    adapter.launch_workflow("preprocessing")

    assert runner.calls == [
        "preprocess-glossary",
        "preprocess-summaries",
        "preprocess-idioms",
        "preprocess-graph",
        "packets-build",
    ]


def test_preprocessing_launch_short_circuits_on_failure():
    from resemantica.tui.adapter import TUIAdapter

    class Runner:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def run_stage(self, stage_name: str, **options):
            self.calls.append(stage_name)

            class Result:
                success = stage_name != "preprocess-summaries"

            return Result()

        def run_production(self, **options):
            return None

    runner = Runner()
    adapter = TUIAdapter("rel", "run", runner=runner)  # type: ignore[arg-type]
    adapter.launch_workflow("preprocessing")

    assert runner.calls == ["preprocess-glossary", "preprocess-summaries"]


def test_chapter_spine_uses_extracted_count():
    from resemantica.tui.screens.base import BaseScreen

    chapter_data = [(i, "not-started") for i in range(1, 6)]
    items = BaseScreen._render_spine_items(chapter_data)
    assert len(items) == 5
    assert items[0] == ("□ Ch 1", "spine-item spine-status-not-started")
    assert items[4] == ("□ Ch 5", "spine-item spine-status-not-started")


def test_chapter_spine_status_chars():
    from resemantica.tui.screens.base import BaseScreen

    chapter_data = [
        (1, "complete"),
        (2, "in-progress"),
        (3, "failed"),
        (4, "high-risk"),
        (5, "not-started"),
    ]
    items = BaseScreen._render_spine_items(chapter_data)
    assert items[0][0].startswith("■")
    assert items[0][1].endswith("spine-status-complete")
    assert items[1][0].startswith("▸")
    assert items[1][1].endswith("spine-status-in-progress")
    assert items[2][0].startswith("✗")
    assert items[2][1].endswith("spine-status-failed")
    assert items[3][0].startswith("◈")
    assert items[3][1].endswith("spine-status-high-risk")
    assert items[4][0].startswith("□")
    assert items[4][1].endswith("spine-status-not-started")


def test_translation_render_block_progress():
    from resemantica.tui.screens.translation import TranslationScreen

    data: dict[int, list[tuple[str, str]]] = {
        1: [("blk001", "done"), ("blk002", "in-progress"), ("blk003", "failed")],
        2: [("blk004", "done")],
    }
    result = TranslationScreen._render_block_progress(data)
    assert "Ch 1" in result
    assert "Ch 2" in result
    assert "1/3 blocks" in result
    assert "1/1 blocks" in result
    assert "blk001" in result
    assert "blk002" in result
    assert "blk003" in result
    assert "blk004" in result


def test_translation_render_block_progress_empty():
    from resemantica.tui.screens.translation import TranslationScreen

    result = TranslationScreen._render_block_progress({})
    assert "No translation run active" in result


def test_launch_control_make_adapter_returns_none_without_context():
    from resemantica.tui.screens.preprocessing import PreprocessingScreen

    screen = PreprocessingScreen()
    adapter = screen._make_adapter()
    assert adapter is None
