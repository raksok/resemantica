from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any


def _iso(hour: int, minute: int, second: int = 0) -> str:
    return datetime(2026, 4, 24, hour, minute, second, tzinfo=timezone.utc).isoformat()


def _make_event(
    *,
    event_type: str,
    event_time: str,
    severity: str = "info",
    message: str = "",
    chapter_number: int | None = None,
    block_id: str | None = None,
    payload: dict[str, Any] | None = None,
):
    from resemantica.tracking.models import Event

    return Event(
        event_type=event_type,
        event_time=event_time,
        run_id="run-1",
        release_id="rel-1",
        stage_name="translate-chapter",
        chapter_number=chapter_number,
        block_id=block_id,
        severity=severity,
        message=message,
        payload=payload or {},
    )


def _strip_markup(text: str) -> str:
    for prefix in ("[comment]", "[cyan]", "[red]"):
        if text.startswith(prefix) and text.endswith("[/]"):
            return text[len(prefix) : -len("[/]")]
    return text


def _static_text(widget) -> str:
    return str(widget.content)


def _button_label(widget) -> str:
    return str(widget.label)


def test_event_bus_subscribe_unsubscribe():
    from resemantica.orchestration.events import emit_event, subscribe, unsubscribe

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
    from resemantica.orchestration.events import emit_event, subscribe, unsubscribe

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
    from resemantica.orchestration.events import emit_event, subscribe, unsubscribe

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


def test_dialog_chapter_bounds_validation():
    from resemantica.tui.screens.run_dialog import parse_chapter_bounds

    assert parse_chapter_bounds("", "") == (None, None, None)
    assert parse_chapter_bounds("2", "5") == (2, 5, None)
    assert parse_chapter_bounds("x", "")[2] == "Chapter start must be a positive integer"
    assert parse_chapter_bounds("", "0")[2] == "Chapter end must be a positive integer"
    assert parse_chapter_bounds("5", "2")[2] == "Chapter end must be greater than or equal to start"


def test_new_file_dialog_callback_saves_bounds(tmp_path):
    from textual.widgets import Input

    from resemantica.tui.app import ResemanticaApp

    epub = tmp_path / "book.epub"
    epub.write_bytes(b"epub")

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#btn-new-file")
            await pilot.pause()

            screen = pilot.app.screen
            screen.query_one("#new-path-input", Input).value = str(epub)
            screen.query_one("#new-release-input", Input).value = "rel-1"
            screen.query_one("#new-run-input", Input).value = "run-1"
            screen.query_one("#new-start-input", Input).value = "2"
            screen.query_one("#new-end-input", Input).value = "4"

            await pilot.click("#new-submit")
            await pilot.pause()

            assert pilot.app.session.input_path == epub.resolve()
            assert pilot.app.release_id == "rel-1"
            assert pilot.app.run_id == "run-1"
            assert pilot.app.session.chapter_start == 2
            assert pilot.app.session.chapter_end == 4

    asyncio.run(run())


def test_resume_run_dialog_callback_saves_bounds():
    from textual.widgets import Input

    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#btn-resume-run")
            await pilot.pause()

            screen = pilot.app.screen
            screen.query_one("#resume-release-input", Input).value = "rel-1"
            screen.query_one("#resume-run-input", Input).value = "run-1"
            screen.query_one("#resume-start-input", Input).value = "3"
            screen.query_one("#resume-end-input", Input).value = "8"

            await pilot.click("#resume-submit")
            await pilot.pause()

            assert pilot.app.session.input_path is None
            assert pilot.app.release_id == "rel-1"
            assert pilot.app.run_id == "run-1"
            assert pilot.app.session.chapter_start == 3
            assert pilot.app.session.chapter_end == 8

    asyncio.run(run())


def test_scoped_launches_pass_chapter_bounds():
    from resemantica.tui.launch_control import (
        LaunchAction,
        LaunchContext,
        LaunchSnapshot,
        LaunchStageStatus,
    )
    from resemantica.tui.screens.dashboard import DashboardScreen
    from resemantica.tui.screens.preprocessing import PreprocessingScreen
    from resemantica.tui.screens.translation import TranslationScreen

    calls: list[tuple[str, dict[str, int]]] = []

    class Adapter:
        def launch_production(self, **options):
            calls.append(("production", options))

        def launch_stage(self, stage_name: str, **options):
            calls.append((stage_name, options))

    def fake_start(action_key, fn):
        fn()

    dashboard = DashboardScreen()
    dashboard._make_adapter = lambda: Adapter()  # type: ignore[method-assign]
    dashboard._chapter_scope_options = lambda: {"chapter_start": 2, "chapter_end": 5}  # type: ignore[method-assign]
    dashboard.start_worker = fake_start  # type: ignore[method-assign]
    dashboard.action_launch_production()

    ready_stage = LaunchStageStatus(
        key="preprocess-glossary",
        label="Glossary",
        status="ready",
        action=LaunchAction(
            key="preprocess-glossary",
            label="Glossary",
            enabled=True,
            reason="",
            shortcut="g",
        ),
        latest_event=None,
        latest_failure=None,
    )
    dashboard._build_snapshot = lambda: LaunchSnapshot(  # type: ignore[method-assign]
        context=LaunchContext(release_id="rel-1", run_id="run-1"),
        active_action=None,
        stages=[ready_stage],
        latest_failure=None,
    )
    dashboard.action_launch_next()

    preprocessing = PreprocessingScreen()
    preprocessing._make_adapter = lambda: Adapter()  # type: ignore[method-assign]
    preprocessing._chapter_scope_options = lambda: {"chapter_start": 2, "chapter_end": 5}  # type: ignore[method-assign]
    preprocessing.start_worker = fake_start  # type: ignore[method-assign]
    preprocessing._launch_stage("packets-build")

    translation = TranslationScreen()
    translation._make_adapter = lambda: Adapter()  # type: ignore[method-assign]
    translation._chapter_scope_options = lambda: {"chapter_start": 2, "chapter_end": 5}  # type: ignore[method-assign]
    translation.start_worker = fake_start  # type: ignore[method-assign]
    translation._launch_stage("translate-range")

    assert calls == [
        ("production", {"chapter_start": 2, "chapter_end": 5}),
        ("preprocess-glossary", {"chapter_start": 2, "chapter_end": 5}),
        ("packets-build", {"chapter_start": 2, "chapter_end": 5}),
        ("translate-range", {"chapter_start": 2, "chapter_end": 5}),
    ]


def test_screen_event_tails_render_filtered_events():
    from resemantica.tui.screens.base import BaseScreen
    from resemantica.tui.screens.ingestion import IngestionScreen
    from resemantica.tui.screens.preprocessing import PreprocessingScreen
    from resemantica.tui.screens.translation import TranslationScreen

    events = [
        _make_event(
            event_type="epub-extract.completed",
            event_time=_iso(12, 1),
            message="extracted",
        ),
        _make_event(
            event_type="preprocess-glossary.completed",
            event_time=_iso(12, 2),
            message="glossary done",
        ),
        _make_event(
            event_type="packets-build.chapter_started",
            event_time=_iso(12, 3),
            message="packet chapter",
            chapter_number=2,
        ),
        _make_event(
            event_type="translate.pass.completed",
            event_time=_iso(12, 4),
            message="pass done",
        ),
    ]
    events[0].stage_name = "epub-extract"
    events[1].stage_name = "preprocess-glossary"
    events[2].stage_name = "packets-build"
    events[3].stage_name = "translate-range"

    dashboard_tail = BaseScreen._render_event_tail(events, title="Recent Events")
    ingestion_events = [
        event
        for event in events
        if IngestionScreen._event_matches_stage_prefix(event, ("epub-extract",))
    ]
    preprocessing_events = [
        event
        for event in events
        if PreprocessingScreen._event_matches_stage_prefix(event, ("preprocess-", "packets-build"))
    ]
    translation_events = [
        event for event in events if TranslationScreen._is_translation_event(event)
    ]

    assert "extracted" in dashboard_tail
    assert "extracted" in IngestionScreen._render_event_tail(ingestion_events, title="Extraction Events")
    preprocessing_tail = PreprocessingScreen._render_event_tail(
        preprocessing_events,
        title="Preprocessing Events",
    )
    assert "glossary done" in preprocessing_tail
    assert "packet chapter" in preprocessing_tail
    assert "pass done" in TranslationScreen._render_event_tail(
        translation_events,
        title="Translation Events",
    )


def test_screen_event_tails_collapse_duplicate_progress_rows():
    from resemantica.tui.screens.base import BaseScreen

    first = _make_event(
        event_type="epub-extract.chapter_started",
        event_time=_iso(12, 1),
        message="Extracting chapter 96",
        chapter_number=96,
    )
    first.stage_name = "epub-extract"
    duplicate = _make_event(
        event_type=first.event_type,
        event_time=_iso(12, 2),
        message=first.message,
        chapter_number=first.chapter_number,
    )
    duplicate.stage_name = first.stage_name

    tail = BaseScreen._render_event_tail([first, duplicate], title="Recent Events")

    assert tail.count("Extracting chapter 96") == 1


def test_tui_screen_event_tail_widgets_render(monkeypatch):
    from textual.widgets import Static

    from resemantica.tui.app import ResemanticaApp
    from resemantica.tui.screens.base import BaseScreen

    events = [
        _make_event(
            event_type="epub-extract.completed",
            event_time=_iso(12, 1),
            message="extracted",
        ),
        _make_event(
            event_type="preprocess-glossary.completed",
            event_time=_iso(12, 2),
            message="glossary done",
        ),
        _make_event(
            event_type="translate.pass.completed",
            event_time=_iso(12, 3),
            message="pass done",
        ),
    ]
    events[0].stage_name = "epub-extract"
    events[1].stage_name = "preprocess-glossary"
    events[2].stage_name = "translate-range"

    monkeypatch.setattr(BaseScreen, "_load_recent_run_events", lambda self, **kwargs: events)
    monkeypatch.setattr(BaseScreen, "_check_extraction_manifest", lambda self: False)

    async def run() -> None:
        app = ResemanticaApp(release_id="rel-1", run_id="run-1")
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            dashboard_tail = pilot.app.screen.query_one("#dashboard-event-tail", Static)
            assert "extracted" in _static_text(dashboard_tail)

            await pilot.press("2")
            await pilot.pause()
            ingestion_tail = pilot.app.screen.query_one("#ingestion-event-tail", Static)
            assert "extracted" in _static_text(ingestion_tail)
            assert "glossary done" not in _static_text(ingestion_tail)

            await pilot.press("3")
            await pilot.pause()
            preprocessing_tail = pilot.app.screen.query_one("#preprocessing-event-tail", Static)
            assert "glossary done" in _static_text(preprocessing_tail)
            assert "pass done" not in _static_text(preprocessing_tail)

            await pilot.press("4")
            await pilot.pause()
            translation_tail = pilot.app.screen.query_one("#translation-event-tail", Static)
            assert "pass done" in _static_text(translation_tail)
            assert "extracted" not in _static_text(translation_tail)

    asyncio.run(run())


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
    assert "◉[/] Glossary" in result
    assert "━━━━━━━━╺─────────" in result
    assert "█" not in result


def test_preprocessing_progress_models_use_scoped_started_totals():
    from resemantica.tui.screens.preprocessing import PreprocessingScreen

    events = [
        _make_event(
            event_type="preprocess-glossary.discover.started",
            event_time=_iso(12, 0),
            payload={"total_chapters": 12},
        ),
        _make_event(
            event_type="preprocess-glossary.discover.chapter_completed",
            event_time=_iso(12, 1),
            chapter_number=1,
        ),
        _make_event(
            event_type="preprocess-glossary.discover.chapter_completed",
            event_time=_iso(12, 2),
            chapter_number=2,
        ),
        _make_event(
            event_type="preprocess-glossary.discover.chapter_skipped",
            event_time=_iso(12, 3),
            chapter_number=3,
        ),
        _make_event(
            event_type="preprocess-glossary.discover.chapter_started",
            event_time=_iso(12, 4),
            chapter_number=4,
        ),
    ]

    model = PreprocessingScreen._derive_progress_models(events)[
        "preprocess-glossary.discover"
    ]

    assert model.total == 12
    assert model.completed == 3
    assert model.active_chapter == 4


def test_preprocessing_render_shows_glossary_parent_and_active_subphase():
    from resemantica.tui.launch_control import (
        LaunchAction,
        LaunchContext,
        LaunchSnapshot,
        LaunchStageStatus,
    )
    from resemantica.tui.screens.preprocessing import PreprocessingScreen

    events = [
        _make_event(
            event_type="preprocess-glossary.discover.started",
            event_time=_iso(12, 0),
            payload={"total_chapters": 12},
        ),
        _make_event(
            event_type="preprocess-glossary.discover.chapter_completed",
            event_time=_iso(12, 1),
            chapter_number=1,
        ),
        _make_event(
            event_type="preprocess-glossary.discover.chapter_skipped",
            event_time=_iso(12, 2),
            chapter_number=2,
        ),
        _make_event(
            event_type="preprocess-glossary.discover.chapter_completed",
            event_time=_iso(12, 3),
            chapter_number=3,
        ),
    ]
    snapshot = LaunchSnapshot(
        context=LaunchContext(release_id="rel-1", run_id="run-1"),
        active_action="preprocess-glossary",
        stages=[
            LaunchStageStatus(
                key="preprocess-glossary",
                label="Glossary",
                status="running",
                action=LaunchAction(
                    key="preprocess-glossary",
                    label="Glossary",
                    enabled=False,
                    reason="",
                    shortcut="g",
                ),
                latest_event=None,
                latest_failure=None,
            )
        ],
        latest_failure=None,
    )

    rendered = PreprocessingScreen()._render_stages_from_snapshot(snapshot, events=events)

    assert "Glossary" in rendered
    assert "discover" in rendered
    assert "3/12" in rendered
    assert "96" not in rendered


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


def test_base_screen_formats_chapter_progress_from_checkpoint_shapes():
    from resemantica.tui.screens.base import BaseScreen

    assert BaseScreen._format_chapter_progress(
        total_chapters=12,
        checkpoint={"chapter_number": 4},
    ) == "Ch 4/12"
    assert BaseScreen._format_chapter_progress(
        total_chapters=12,
        checkpoint={"completed_chapters": [1, 3], "pass2_completed": [5, 7]},
    ) == "Ch 7/12"
    assert BaseScreen._format_chapter_progress(
        total_chapters=12,
        checkpoint={"chapter_number": 2, "pass3_completed": [9]},
    ) == "Ch 2/12"


def test_base_screen_maps_pass_labels_for_supported_stages():
    from resemantica.tui.screens.base import BaseScreen

    extract_state = {"stage_name": "epub-extract", "status": "running", "checkpoint": {}}
    assert BaseScreen._derive_pass_indicator(extract_state, []) == ("EXTRACT", "cyan")

    preprocess_state = {"stage_name": "preprocess-glossary", "status": "running", "checkpoint": {}}
    assert BaseScreen._derive_pass_indicator(preprocess_state, []) == ("PREPROCESS", "comment")

    pass1_state = {"stage_name": "translate-range", "status": "running", "checkpoint": {}}
    assert BaseScreen._derive_pass_indicator(pass1_state, []) == ("PASS 1", "cyan")

    pass2_state = {
        "stage_name": "translate-range",
        "status": "running",
        "checkpoint": {"pass2_completed": [1]},
    }
    assert BaseScreen._derive_pass_indicator(pass2_state, []) == ("PASS 2", "cyan")

    pass3_state = {"stage_name": "translate-chapter", "status": "running", "checkpoint": {}}
    pass3_events = [
        _make_event(
            event_type="paragraph_completed",
            event_time=_iso(12, 10),
            payload={"pass_name": "pass3"},
        )
    ]
    assert BaseScreen._derive_pass_indicator(pass3_state, pass3_events) == ("PASS 3", "cyan")

    rebuild_state = {"stage_name": "epub-rebuild", "status": "running", "checkpoint": {}}
    assert BaseScreen._derive_pass_indicator(rebuild_state, pass3_events) == ("REBUILD", "green")

    unknown_state = {"stage_name": "custom-stage", "status": "running", "checkpoint": {}}
    assert BaseScreen._derive_pass_indicator(unknown_state, []) == ("RUNNING", "cyan")

    idle_state = {"stage_name": "translate-range", "status": "completed", "checkpoint": {}}
    assert BaseScreen._derive_pass_indicator(idle_state, pass3_events) == ("IDLE", "comment")
    assert BaseScreen._derive_pass_indicator(None, pass3_events) == ("IDLE", "comment")


def test_base_screen_renders_30_char_pulse_bar_with_expected_glyphs():
    from resemantica.tui.screens.base import BaseScreen

    state = {
        "stage_name": "translate-range",
        "status": "running",
        "started_at": _iso(12, 0),
        "finished_at": None,
        "checkpoint": {},
    }
    events = [
        _make_event(event_type="paragraph_completed", event_time=_iso(12, 2), block_id="blk-1"),
        _make_event(event_type="paragraph_completed", event_time=_iso(12, 8), block_id="blk-2"),
        _make_event(event_type="paragraph_completed", event_time=_iso(12, 16), block_id="blk-3"),
        _make_event(event_type="paragraph_completed", event_time=_iso(12, 24), block_id="blk-4"),
    ]

    pulse = BaseScreen._render_pulse_bar(
        state,
        events,
        now=datetime(2026, 4, 24, 12, 24, 30, tzinfo=timezone.utc),
    )
    rendered = _strip_markup(pulse)

    assert pulse.startswith("[cyan]")
    assert len(rendered) == 30
    assert set(rendered) <= set(BaseScreen._PULSE_GLYPHS)


def test_base_screen_renders_idle_active_and_retry_pulse_states():
    from resemantica.tui.screens.base import BaseScreen

    assert BaseScreen._render_pulse_bar(None, []) == f"[comment]{'▁' * 30}[/]"

    state = {
        "stage_name": "translate-range",
        "status": "running",
        "started_at": _iso(12, 0),
        "finished_at": None,
        "checkpoint": {},
    }
    active_events = [
        _make_event(event_type="paragraph_completed", event_time=_iso(12, 5), block_id="blk-1"),
    ]
    retry_events = active_events + [
        _make_event(event_type="paragraph_retry", event_time=_iso(12, 6), block_id="blk-1"),
    ]

    active = BaseScreen._render_pulse_bar(
        state,
        active_events,
        now=datetime(2026, 4, 24, 12, 5, 30, tzinfo=timezone.utc),
    )
    retry = BaseScreen._render_pulse_bar(
        state,
        retry_events,
        now=datetime(2026, 4, 24, 12, 6, 30, tzinfo=timezone.utc),
    )

    assert active.startswith("[cyan]")
    assert retry.startswith("[red]")


def test_base_screen_marks_stale_running_state_from_event_age():
    from resemantica.tui.screens.base import BaseScreen

    state = {
        "stage_name": "preprocess-graph",
        "status": "running",
        "started_at": _iso(12, 0),
        "finished_at": None,
        "checkpoint": {},
    }
    events = [
        _make_event(
            event_type="preprocess-graph.chapter_started",
            event_time=_iso(12, 1),
        )
    ]
    now = datetime.fromisoformat(_iso(12, 1)) + timedelta(seconds=301)

    assert BaseScreen._is_run_stale(state, events, now=now)
    assert "STALE" in BaseScreen._format_status_label(state, events, now=now)
    assert BaseScreen._render_pulse_bar(state, events, now=now).startswith("[orange]")


def test_base_screen_formats_running_status_with_spinner():
    from resemantica.tui.screens.base import BaseScreen

    state = {
        "stage_name": "preprocess-graph",
        "status": "running",
        "started_at": _iso(12, 0),
        "finished_at": None,
        "checkpoint": {},
    }
    events = [_make_event(event_type="preprocess-graph.started", event_time=_iso(12, 0))]
    now = datetime.fromisoformat(_iso(12, 0)) + timedelta(seconds=5)

    rendered = BaseScreen._format_status_label(state, events, now=now)

    assert "RUNNING" in rendered
    assert any(glyph in rendered for glyph in BaseScreen._SPINNER_GLYPHS)


def test_tui_spinner_refresh_does_not_reload_run_data():
    from textual.widgets import Static

    from resemantica.tui.screens.base import HeaderPassIndicator
    from resemantica.tui.screens.dashboard import DashboardScreen

    screen = DashboardScreen()
    screen._header_pass_indicator = HeaderPassIndicator(
        label="PREPROCESS",
        color="cyan",
        running=True,
    )

    def fail_load(*args, **kwargs):
        raise AssertionError("spinner refresh should not load run data")

    screen._get_run_state = fail_load  # type: ignore[method-assign]
    screen._load_recent_run_events = fail_load  # type: ignore[method-assign]
    screen.query_one = lambda selector, widget_type=None: Static(id="header-pass")  # type: ignore[method-assign]

    screen._refresh_header_pass()


def test_tui_fast_refresh_skips_heavy_loaders_during_active_action(monkeypatch):
    from resemantica.tui.app import ResemanticaApp
    from resemantica.tui.screens.base import BaseScreen

    def fail_load(*args, **kwargs):
        raise AssertionError("active action refresh should use cached data")

    monkeypatch.setattr(BaseScreen, "_get_run_state", fail_load)
    monkeypatch.setattr(BaseScreen, "_load_recent_run_events", fail_load)
    monkeypatch.setattr(BaseScreen, "_load_chapter_count", fail_load)
    monkeypatch.setattr(BaseScreen, "_check_extraction_manifest", fail_load)
    monkeypatch.setattr(BaseScreen, "_update_spine", fail_load)

    async def run() -> None:
        app = ResemanticaApp(release_id="rel-1", run_id="run-1")
        app.active_action = "epub-extract"
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            pilot.app.screen._refresh_all()

    asyncio.run(run())


def test_ingestion_fast_refresh_renders_extracting_without_manifest_loads(monkeypatch):
    from pathlib import Path

    from textual.widgets import Static

    from resemantica.tui.app import ResemanticaApp
    from resemantica.tui.screens.base import BaseScreen

    def fail_load(*args, **kwargs):
        raise AssertionError("ingestion extraction refresh should not load artifacts")

    monkeypatch.setattr(BaseScreen, "_load_recent_run_events", fail_load)
    monkeypatch.setattr(BaseScreen, "_get_run_state", fail_load)
    monkeypatch.setattr(BaseScreen, "_load_chapter_count", fail_load)
    monkeypatch.setattr(BaseScreen, "_check_extraction_manifest", fail_load)
    monkeypatch.setattr(BaseScreen, "_update_spine", fail_load)

    async def run() -> None:
        app = ResemanticaApp(release_id="rel-1", run_id="run-1")
        app.active_action = "epub-extract"
        app.session.input_path = Path("book.epub")
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.press("2")
            await pilot.pause()

            status = pilot.app.screen.query_one("#ingestion-status", Static)
            assert "Extracting" in _static_text(status)

    asyncio.run(run())


def test_tui_preprocessing_event_tail_shows_live_events_without_heavy_loaders(monkeypatch):
    from textual.widgets import Static

    from resemantica.tui.app import ResemanticaApp
    from resemantica.tui.screens.base import BaseScreen

    def fail_load(*args, **kwargs):
        raise AssertionError("live progress refresh should not load persisted artifacts")

    monkeypatch.setattr(BaseScreen, "_load_recent_run_events", fail_load)
    monkeypatch.setattr(BaseScreen, "_get_run_state", fail_load)
    monkeypatch.setattr(BaseScreen, "_load_chapter_count", fail_load)
    monkeypatch.setattr(BaseScreen, "_check_extraction_manifest", fail_load)
    monkeypatch.setattr(BaseScreen, "_update_spine", fail_load)

    event = _make_event(
        event_type="preprocess-glossary.chapter_completed",
        event_time=_iso(12, 1),
        message="live glossary chapter",
        chapter_number=3,
    )
    event.stage_name = "preprocess-glossary"

    async def run() -> None:
        app = ResemanticaApp(release_id="rel-1", run_id="run-1")
        app.active_action = "preprocess-glossary"
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.press("3")
            await pilot.pause()

            pilot.app._on_live_event(event)
            pilot.app._drain_live_events()
            await pilot.pause()

            tail = pilot.app.screen.query_one("#preprocessing-event-tail", Static)
            assert "live glossary chapter" in _static_text(tail)
            assert "Updates resume when action completes" not in _static_text(tail)

    asyncio.run(run())


def test_tui_dashboard_event_tail_shows_live_active_action_events(monkeypatch):
    from textual.widgets import Static

    from resemantica.tui.app import ResemanticaApp
    from resemantica.tui.screens.base import BaseScreen

    def fail_load(*args, **kwargs):
        raise AssertionError("live dashboard refresh should not load persisted artifacts")

    monkeypatch.setattr(BaseScreen, "_load_recent_run_events", fail_load)
    monkeypatch.setattr(BaseScreen, "_get_run_state", fail_load)
    monkeypatch.setattr(BaseScreen, "_load_chapter_count", fail_load)
    monkeypatch.setattr(BaseScreen, "_check_extraction_manifest", fail_load)
    monkeypatch.setattr(BaseScreen, "_update_spine", fail_load)

    event = _make_event(
        event_type="preprocess-summaries.chapter_completed",
        event_time=_iso(12, 2),
        message="live dashboard progress",
        chapter_number=4,
    )
    event.stage_name = "preprocess-summaries"

    async def run() -> None:
        app = ResemanticaApp(release_id="rel-1", run_id="run-1")
        app.active_action = "preprocess-summaries"
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()

            pilot.app._on_live_event(event)
            pilot.app._drain_live_events()
            await pilot.pause()

            tail = pilot.app.screen.query_one("#dashboard-event-tail", Static)
            assert "live dashboard progress" in _static_text(tail)

    asyncio.run(run())


def test_tui_live_events_refresh_only_on_tick():
    from resemantica.tui.app import ResemanticaApp

    event = _make_event(
        event_type="preprocess-glossary.chapter_completed",
        event_time=_iso(12, 3),
        message="batched progress",
    )
    event.stage_name = "preprocess-glossary"

    async def run() -> None:
        app = ResemanticaApp(release_id="rel-1", run_id="run-1")
        app.active_action = "preprocess-glossary"
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            calls = 0

            def record_refresh() -> None:
                nonlocal calls
                calls += 1

            pilot.app.screen._refresh_live_progress = record_refresh  # type: ignore[method-assign]

            for _ in range(25):
                pilot.app._on_live_event(event)

            assert calls == 0
            pilot.app._drain_live_events()
            assert calls == 1

    asyncio.run(run())


def test_tui_cached_and_live_duplicate_events_render_once():
    from textual.widgets import Static

    from resemantica.tui.app import ResemanticaApp

    event = _make_event(
        event_type="preprocess-glossary.chapter_completed",
        event_time=_iso(12, 4),
        message="deduped live event",
    )
    event.stage_name = "preprocess-glossary"

    async def run() -> None:
        app = ResemanticaApp(release_id="rel-1", run_id="run-1")
        app.active_action = "preprocess-glossary"
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            pilot.app.screen._store_refresh_cache(events=[event])

            pilot.app._on_live_event(event)
            pilot.app._drain_live_events()
            await pilot.pause()

            tail = pilot.app.screen.query_one("#dashboard-event-tail", Static)
            assert _static_text(tail).count("deduped live event") == 1

    asyncio.run(run())


def test_tui_header_pass_prefers_active_action_when_run_state_empty():
    from textual.widgets import Static

    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp(release_id="rel-1", run_id="run-1")
        app.active_action = "translate-range"
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()

            header_pass = pilot.app.screen.query_one("#header-pass", Static)
            assert "PASS 1" in _static_text(header_pass)
            assert "IDLE" not in _static_text(header_pass)

    asyncio.run(run())


def test_worker_success_clears_active_action_before_full_refresh(monkeypatch):
    from resemantica.tui.app import ResemanticaApp
    from resemantica.tui.screens.base import BaseScreen

    calls: list[str] = []

    def record(name: str):
        def inner(self, *args, **kwargs):
            assert getattr(self.app, "active_action", None) is None
            calls.append(name)
            if name == "events":
                return []
            if name == "chapter_count":
                return 0
            if name == "manifest":
                return False
            return None

        return inner

    def record_spine(self):
        assert getattr(self.app, "active_action", None) is None
        calls.append("spine")

    monkeypatch.setattr(BaseScreen, "_get_run_state", record("state"))
    monkeypatch.setattr(BaseScreen, "_load_recent_run_events", record("events"))
    monkeypatch.setattr(BaseScreen, "_load_chapter_count", record("chapter_count"))
    monkeypatch.setattr(BaseScreen, "_check_extraction_manifest", record("manifest"))
    monkeypatch.setattr(BaseScreen, "_update_spine", record_spine)

    async def run() -> None:
        app = ResemanticaApp(release_id="rel-1", run_id="run-1")
        app.active_action = "epub-extract"
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            calls.clear()

            pilot.app.screen._on_worker_success("epub-extract", {})

            assert pilot.app.active_action is None
            assert {"state", "events", "chapter_count", "spine", "manifest"}.issubset(calls)

    asyncio.run(run())


def test_base_screen_derives_footer_metrics_from_events():
    from resemantica.tui.screens.base import BaseScreen

    state = {
        "stage_name": "translate-range",
        "status": "running",
        "started_at": _iso(12, 0),
        "finished_at": _iso(14, 3, 4),
        "checkpoint": {},
    }
    events = [
        _make_event(event_type="paragraph_started", event_time=_iso(12, 1), block_id="blk-1"),
        _make_event(event_type="paragraph_completed", event_time=_iso(12, 2), block_id="blk-1"),
        _make_event(event_type="paragraph_started", event_time=_iso(12, 3), block_id="blk-2"),
        _make_event(
            event_type="validation_failed",
            event_time=_iso(12, 4),
            severity="warning",
            message="warning",
        ),
        _make_event(
            event_type="stage_failed",
            event_time=_iso(12, 5),
            severity="error",
            message="failure",
        ),
    ]

    metrics = BaseScreen._derive_footer_metrics(state, events)

    assert metrics["block_progress"] == "1/2 blocks"
    assert metrics["warnings"] == "Warn 1"
    assert metrics["failures"] == "Fail 1"
    assert metrics["elapsed"] == "2:03:04"


def test_dashboard_quick_stats_aggregate_actual_event_names():
    from resemantica.tui.screens.dashboard import DashboardScreen

    events = [
        _make_event(event_type="preprocess-glossary.discover.term_found", event_time=_iso(12, 1)),
        _make_event(event_type="preprocess-glossary.discover.term_found", event_time=_iso(12, 2)),
        _make_event(
            event_type="preprocess-idioms.completed",
            event_time=_iso(12, 3),
            payload={"promoted_count": 3},
        ),
        _make_event(event_type="preprocess-graph.entity_extracted", event_time=_iso(12, 4)),
        _make_event(event_type="preprocess-graph.entity_extracted", event_time=_iso(12, 5)),
        _make_event(event_type="paragraph_retry", event_time=_iso(12, 6)),
        _make_event(event_type="stage.retry", event_time=_iso(12, 7)),
        _make_event(
            event_type="risk_detected",
            event_time=_iso(12, 8),
            payload={"risk_score": 0.6},
        ),
        _make_event(
            event_type="risk_detected",
            event_time=_iso(12, 9),
            payload={"risk_score": 0.8},
        ),
    ]

    result = DashboardScreen._build_quick_stats_from_events(events)

    assert "Glossary     2 terms" in result
    assert "Idioms       3 policies" in result
    assert "Entities     2 extracted" in result
    assert "Retries      2 total" in result
    assert "Avg risk     0.70" in result


def test_dashboard_quick_stats_empty_state():
    from resemantica.tui.screens.dashboard import DashboardScreen

    result = DashboardScreen._build_quick_stats_from_events([])

    assert "Quick stats unavailable for this run yet." in result


def test_dashboard_recent_warnings_requires_active_run():
    from resemantica.tui.screens.dashboard import DashboardScreen

    screen = DashboardScreen()
    screen._get_release_id = lambda: "rel-1"  # type: ignore[method-assign]
    screen._get_run_id = lambda: None  # type: ignore[method-assign]

    result = screen._build_recent_warnings()

    assert result == "[dim]No warnings.[/]"


def test_dashboard_event_summary_uses_event_type_when_message_empty():
    from resemantica.tui.screens.dashboard import DashboardScreen

    event = _make_event(
        event_type="preprocess-graph.chapter_skipped",
        event_time=_iso(12, 1),
        message="",
        chapter_number=20,
        payload={"reason": "non_story_chapter"},
    )

    rendered = DashboardScreen._format_event_summary(event)

    assert "preprocess-graph.chapter_skipped" in rendered
    assert "ch=20" in rendered
    assert "reason=non_story_chapter" in rendered


def test_dashboard_recent_warnings_scopes_events_to_active_run(monkeypatch):
    from resemantica.tui.screens.dashboard import DashboardScreen

    captured: dict[str, object] = {}

    class _Conn:
        def close(self) -> None:
            pass

    def fake_ensure_tracking_db(release_id: str):
        captured["release_id"] = release_id
        return _Conn()

    def fake_load_events(conn, run_id=None, release_id=None, limit=100):
        captured["run_id"] = run_id
        captured["event_release_id"] = release_id
        captured["limit"] = limit
        return [
            _make_event(
                event_type="risk_detected",
                event_time=_iso(12, 1),
                severity="warning",
                message="scoped warning",
            )
        ]

    monkeypatch.setattr("resemantica.tracking.repo.ensure_tracking_db", fake_ensure_tracking_db)
    monkeypatch.setattr("resemantica.tracking.repo.load_events", fake_load_events)

    screen = DashboardScreen()
    screen._get_release_id = lambda: "rel-1"  # type: ignore[method-assign]
    screen._get_run_id = lambda: "run-1"  # type: ignore[method-assign]

    result = screen._build_recent_warnings()

    assert captured == {
        "release_id": "rel-1",
        "run_id": "run-1",
        "event_release_id": "rel-1",
        "limit": 5,
    }
    assert "scoped warning" in result


def test_tui_dashboard_mount_refresh_is_idempotent():
    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            dashboard = pilot.app.screen

            assert len(list(dashboard.query("#spine-title"))) == 1
            assert len(list(dashboard.query("#spine-items > .spine-item"))) == 1

            dashboard._refresh_all()
            await pilot.pause()

            assert len(list(dashboard.query("#spine-title"))) == 1
            assert len(list(dashboard.query("#spine-items > .spine-item"))) == 1

    asyncio.run(run())


def test_tui_shell_places_main_content_beside_spine():
    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            spine = screen.query_one("#spine-container")
            main = screen.query_one("#main-content")

            assert main.region.x >= spine.region.x + spine.region.width
            assert main.region.y <= spine.region.y + 1

    asyncio.run(run())


def test_tui_dashboard_event_tail_uses_right_split_panel():
    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            left = pilot.app.screen.query_one("#dashboard-left")
            event_panel = pilot.app.screen.query_one("#dashboard-event-panel")
            event_tail = pilot.app.screen.query_one("#dashboard-event-tail")

            assert event_panel.region.x >= left.region.x + left.region.width
            assert event_tail.region.y <= left.region.y + 1
            assert abs((left.region.width / event_panel.region.width) - 1.5) < 0.2

    asyncio.run(run())


def test_tui_observability_warnings_bottom_pane():
    from textual.widgets import DataTable

    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test() as pilot:
            await pilot.press("5")
            await pilot.pause()

            table = pilot.app.screen.query_one("#observability-warnings-table", DataTable)

            assert table.row_count == 1
            assert len(table.ordered_columns) == 3

    asyncio.run(run())


def test_tui_header_and_footer_show_current_screen_location():
    from textual.widgets import Static

    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            header = pilot.app.screen.query_one("#header-screen-location", Static)
            footer = pilot.app.screen.query_one("#footer-keys", Static)
            assert _static_text(header) == "Screen 1/7 Dashboard"
            assert "Active: 1 Dashboard" in _static_text(footer)
            assert "? Help" in _static_text(footer)

            await pilot.press("4")
            await pilot.pause()
            header = pilot.app.screen.query_one("#header-screen-location", Static)
            assert _static_text(header) == "Screen 4/7 Translation"

            await pilot.press("7")
            await pilot.pause()
            header = pilot.app.screen.query_one("#header-screen-location", Static)
            assert _static_text(header) == "Screen 7/7 Settings"

    asyncio.run(run())


def test_tui_help_modal_lists_navigation_and_returns_to_prior_screen():
    from textual.widgets import Static

    from resemantica.tui.app import ResemanticaApp
    from resemantica.tui.screens.settings import SettingsScreen

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test() as pilot:
            await pilot.press("7")
            await pilot.pause()

            await pilot.press("?")
            await pilot.pause()

            assert pilot.app.screen.styles.background.a == 0
            help_dialog = pilot.app.screen.query_one("#help-dialog")
            assert help_dialog.region.x + help_dialog.region.width >= pilot.app.size.width - 2

            help_content = pilot.app.screen.query_one("#help-content", Static)
            rendered = _static_text(help_content)

            assert "Screen 7/7 Settings" in rendered
            for label in (
                "Dashboard",
                "Ingestion",
                "Preprocessing",
                "Translation",
                "Observability",
                "Artifact",
                "Settings",
            ):
                assert label in rendered
            assert "1-7 Switch" in rendered
            assert "? Help" in rendered
            assert "v=Verbose" in rendered
            assert "r=Refresh" in rendered

            await pilot.press("escape")
            await pilot.pause()

            assert isinstance(pilot.app.screen, SettingsScreen)

    asyncio.run(run())


def test_tui_run_dialogs_are_centered_transparent_and_compact():
    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            await pilot.click("#btn-new-file")
            await pilot.pause()

            new_screen = pilot.app.screen
            new_dialog = new_screen.query_one("#new-file-dialog")

            assert new_screen.styles.background.a == 0
            assert new_dialog.region.x > 0
            assert new_dialog.region.y > 0
            assert new_dialog.region.x + new_dialog.region.width <= pilot.app.size.width
            assert new_dialog.region.y + new_dialog.region.height <= pilot.app.size.height
            assert new_dialog.region.height <= 18

            await pilot.press("escape")
            await pilot.pause()

            await pilot.click("#btn-resume-run")
            await pilot.pause()

            resume_screen = pilot.app.screen
            resume_dialog = resume_screen.query_one("#resume-run-dialog")

            assert resume_screen.styles.background.a == 0
            assert resume_dialog.region.x > 0
            assert resume_dialog.region.y > 0
            assert resume_dialog.region.x + resume_dialog.region.width <= pilot.app.size.width
            assert resume_dialog.region.y + resume_dialog.region.height <= pilot.app.size.height
            assert resume_dialog.region.height <= 15

    asyncio.run(run())


def test_tui_command_buttons_use_unified_bracket_labels():
    from textual.widgets import Button

    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            assert _button_label(pilot.app.screen.query_one("#btn-new-file", Button)) == "[[ NEW FILE ]]"
            assert _button_label(pilot.app.screen.query_one("#btn-resume-run", Button)) == "[[ RESUME RUN ]]"

            await pilot.click("#btn-new-file")
            await pilot.pause()

            assert _button_label(pilot.app.screen.query_one("#new-submit", Button)) == "[[ SUBMIT ]]"
            assert _button_label(pilot.app.screen.query_one("#new-cancel", Button)) == "[[ CANCEL ]]"

            await pilot.press("escape")
            await pilot.pause()

            await pilot.click("#btn-resume-run")
            await pilot.pause()

            assert _button_label(pilot.app.screen.query_one("#resume-submit", Button)) == "[[ SUBMIT ]]"
            assert _button_label(pilot.app.screen.query_one("#resume-cancel", Button)) == "[[ CANCEL ]]"

    asyncio.run(run())
