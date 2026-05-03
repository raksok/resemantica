from __future__ import annotations

import asyncio

from textual.widgets import Static, Tree


def test_categorize():
    from resemantica.tui.screens.cleanup_wizard import _categorize

    assert _categorize("/releases/rel-1/runs/run-abc/") == "Run directory"
    assert _categorize("/releases/rel-1/runs/run-abc/translation/ch5") == "Translation output"
    assert _categorize("/releases/rel-1/extracted/") == "Extracted text"
    assert _categorize("/releases/rel-1/glossary/") == "Glossary candidates"
    assert _categorize("/releases/rel-1/summaries/") == "Draft summaries"
    assert _categorize("/releases/rel-1/idioms/") == "Idiom policies"
    assert _categorize("/releases/rel-1/graph/") == "Knowledge graph"
    assert _categorize("/releases/rel-1/packets/") == "Chapter packets"
    assert _categorize("/releases/rel-1/.cache/") == "LLM cache"
    assert _categorize("/releases/rel-1/other.txt") == "Other"


def test_format_size():
    from resemantica.tui.screens.cleanup_wizard import _format_size

    assert _format_size(500) == "500 B"
    assert _format_size(2048) == "2.0 KB"
    assert _format_size(1048576) == "1.0 MB"
    assert _format_size(-1) == "unknown"


def test_wizard_state_machine():
    from resemantica.tui.screens.cleanup_wizard import CleanupWizardScreen

    screen = CleanupWizardScreen()
    screen._render_step = lambda: None
    screen._refresh_plan = lambda: None

    screen._step = 1
    screen._scope_index = 0
    screen._scope = "run"

    screen.action_preview_or_advance()
    assert screen._step == 2

    screen.action_preview_or_advance()
    assert screen._step == 3

    screen.action_back()
    assert screen._step == 2

    screen.action_back()
    assert screen._step == 1

    screen.action_back()
    assert screen._step == 1


def test_wizard_scope_cycle():
    from resemantica.tui.screens.cleanup_wizard import SCOPES, CleanupWizardScreen

    screen = CleanupWizardScreen()
    screen._render_step = lambda: None
    screen._refresh_plan = lambda: None

    screen._step = 1
    screen._scope_index = 0
    screen._scope = "run"

    for _ in range(len(SCOPES)):
        screen.action_cycle_scope()

    assert screen._scope_index == 0
    assert screen._scope == "run"


def test_wizard_factory_in_scopes():
    from resemantica.tui.screens.cleanup_wizard import SCOPES

    assert "factory" in SCOPES
    assert SCOPES[-1] == "factory"
    assert len(SCOPES) == 6


def test_wizard_scope_cycle_resets_to_step_1():
    from resemantica.tui.screens.cleanup_wizard import CleanupWizardScreen

    screen = CleanupWizardScreen()
    screen._render_step = lambda: None
    screen._refresh_plan = lambda: None

    screen._step = 2
    screen._scope_index = 0
    screen._scope = "run"

    screen.action_cycle_scope()
    assert screen._step == 1


def test_wizard_apply_guarded_on_wrong_step():
    from resemantica.tui.screens.cleanup_wizard import CleanupWizardScreen

    screen = CleanupWizardScreen()
    screen._render_step = lambda: None
    screen._refresh_plan = lambda: None

    screen._step = 1
    screen.action_confirm_and_apply()
    assert screen._step == 1

    screen._step = 2
    screen.action_confirm_and_apply()
    assert screen._step == 2


def test_wizard_preview_or_advance_past_step_3_noop():
    from resemantica.tui.screens.cleanup_wizard import CleanupWizardScreen

    screen = CleanupWizardScreen()
    screen._render_step = lambda: None
    screen._refresh_plan = lambda: None

    screen._step = 4
    screen.action_preview_or_advance()
    assert screen._step == 4


def test_artifact_has_no_cleanup_attributes():
    from resemantica.tui.screens.artifact import ArtifactScreen

    screen = ArtifactScreen()
    assert not hasattr(screen, "_scope")
    assert not hasattr(screen, "_preview_done")


def test_wizard_has_no_old_cleanup_attributes():
    from resemantica.tui.screens.cleanup_wizard import CleanupWizardScreen

    screen = CleanupWizardScreen()
    assert not hasattr(screen, "_preview_done")


def test_navigation_8_screens():
    from resemantica.tui.navigation import SCREEN_INFOS, TOTAL_PRIMARY_SCREENS

    assert TOTAL_PRIMARY_SCREENS == 8
    assert SCREEN_INFOS[6].screen_id == "cleanup-wizard"
    assert SCREEN_INFOS[6].number == 7
    assert SCREEN_INFOS[7].screen_id == "settings"
    assert SCREEN_INFOS[7].number == 8


def test_navigation_format_location():
    from resemantica.tui.navigation import SCREEN_INFOS, format_location

    cleanup_info = SCREEN_INFOS[6]
    rendered = format_location(cleanup_info)
    assert "Screen 7/8" in rendered
    assert "Cleanup" in rendered

    settings_info = SCREEN_INFOS[7]
    rendered = format_location(settings_info)
    assert "Screen 8/8" in rendered
    assert "Settings" in rendered


def test_settings_screen_still_works():
    from resemantica.tui.screens.settings import SettingsScreen

    screen = SettingsScreen()
    result = screen._build_config_text()
    assert "Models" in result
    assert "LLM" in result
    assert "Paths" in result
    assert "Budget" in result
    assert "Translation" in result


def test_mounted_wizard_renders_step_1():
    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.press("7")
            await pilot.pause()

            step_indicator = pilot.app.screen.query_one("#wizard-step-indicator", Static)
            rendered = str(step_indicator.content)
            assert "Cleanup Wizard" in rendered
            assert "Step 1/4" in rendered

            scope_info = pilot.app.screen.query_one("#wizard-scope-info", Static)
            scope_text = str(scope_info.content)
            assert "run" in scope_text

            main = pilot.app.screen.query_one("#wizard-main-content", Static)
            main_text = str(main.content)
            # Without release/run context, shows guidance message
            assert "No release or run context" in main_text

    asyncio.run(run())


def test_mounted_wizard_scope_cycle_updates_display():
    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.press("7")
            await pilot.pause()

            scope_info = pilot.app.screen.query_one("#wizard-scope-info", Static)

            await pilot.press("s")
            await pilot.pause()
            assert "translation" in str(scope_info.content)

            await pilot.press("s")
            await pilot.pause()
            assert "preprocess" in str(scope_info.content)

            await pilot.press("s")
            await pilot.pause()
            assert "cache" in str(scope_info.content)

            await pilot.press("s")
            await pilot.pause()
            assert "all" in str(scope_info.content)

            await pilot.press("s")
            await pilot.pause()
            assert "factory" in str(scope_info.content)

            await pilot.press("s")
            await pilot.pause()
            assert "run" in str(scope_info.content)

    asyncio.run(run())


def test_mounted_wizard_back_and_forth():
    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.press("7")
            await pilot.pause()

            step_indicator = pilot.app.screen.query_one("#wizard-step-indicator", Static)

            await pilot.press("p")
            await pilot.pause()
            assert "Step 2/4" in str(step_indicator.content)

            await pilot.press("p")
            await pilot.pause()
            assert "Step 3/4" in str(step_indicator.content)

            await pilot.press("b")
            await pilot.pause()
            assert "Step 2/4" in str(step_indicator.content)

            await pilot.press("b")
            await pilot.pause()
            assert "Step 1/4" in str(step_indicator.content)

    asyncio.run(run())


def test_mounted_wizard_escape_returns_to_artifact():
    from resemantica.tui.app import ResemanticaApp
    from resemantica.tui.navigation import format_location, screen_info_for_class_name

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.press("7")
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

            info = screen_info_for_class_name(pilot.app.screen.__class__.__name__)
            rendered = format_location(info)
            assert "Artifact" in rendered

    asyncio.run(run())


def test_mounted_artifact_has_no_cleanup():
    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.press("6")
            await pilot.pause()

            assert pilot.app.screen.query_one("#artifact-tree", Tree) is not None
            assert pilot.app.screen.query_one("#artifact-tree-section") is not None

    asyncio.run(run())


def test_help_shows_8_screens():
    from resemantica.tui.screens.help import HelpScreen

    help_screen = HelpScreen()
    text = help_screen._build_help_text()

    assert "[b]Cleanup[/]" in text
    assert "1-8 Switch" in text
    assert "s=Scope" in text
    assert "a=Apply" in text


def test_mounted_wizard_content_widgets():
    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.press("7")
            await pilot.pause()

            screen = pilot.app.screen
            assert screen.query_one("#wizard-step-indicator", Static) is not None
            assert screen.query_one("#wizard-scope-info", Static) is not None
            assert screen.query_one("#wizard-main-content", Static) is not None
            assert screen.query_one("#wizard-key-hints", Static) is not None

    asyncio.run(run())


def test_mounted_wizard_spine_visible():
    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.press("7")
            await pilot.pause()

            spine = pilot.app.screen.query_one("#spine-container")
            assert "spine-hidden" not in spine.classes

    asyncio.run(run())


def test_mounted_wizard_factory_shows_warning_on_step_1():
    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.press("7")
            await pilot.pause()

            # Cycle to factory (5 presses: trans, preprocess, cache, all, factory)
            for _ in range(5):
                await pilot.press("s")
                await pilot.pause()

            scope_info = pilot.app.screen.query_one("#wizard-scope-info", Static)
            assert "factory" in str(scope_info.content)

            main = pilot.app.screen.query_one("#wizard-main-content", Static)
            main_text = str(main.content)
            assert "FACTORY RESET" in main_text
            assert "ALL releases" in main_text

    asyncio.run(run())


def test_mounted_wizard_factory_confirm_shows_warning():
    from resemantica.tui.app import ResemanticaApp

    async def run() -> None:
        app = ResemanticaApp()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.press("7")
            await pilot.pause()

            # Cycle to factory then advance to confirm
            for _ in range(5):
                await pilot.press("s")
                await pilot.pause()

            await pilot.press("p")
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()

            main = pilot.app.screen.query_one("#wizard-main-content", Static)
            main_text = str(main.content)
            assert "FACTORY RESET" in main_text
            assert "ALL releases" in main_text
            assert "ALL runs" in main_text
            assert "global database" in main_text.lower()

    asyncio.run(run())


def test_categorize_factory_paths():
    from resemantica.tui.screens.cleanup_wizard import _categorize

    assert _categorize("/tmp/artifacts/releases") == "All releases"
    assert _categorize("/tmp/artifacts/resemantica.db") == "Global database"
