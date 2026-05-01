from __future__ import annotations

from pathlib import Path

from textual.app import App
from textual.binding import Binding

from resemantica.tui.screens import (
    DashboardScreen,
    PreprocessingScreen,
    TranslationScreen,
    WarningsScreen,
    ArtifactsScreen,
    CleanupScreen,
    EventLogScreen,
    ResetPreviewScreen,
    SettingsScreen,
    HelpScreen,
)
from resemantica.tui.navigation import SCREEN_INFOS, screen_info_for_class_name


class ResemanticaApp(App):
    TITLE = "Resemantica"
    SUB_TITLE = "Translation Pipeline"
    CSS_PATH = "palenight.tcss"

    SCREENS = {
        "dashboard": DashboardScreen,
        "preprocessing": PreprocessingScreen,
        "translation": TranslationScreen,
        "warnings": WarningsScreen,
        "artifacts": ArtifactsScreen,
        "cleanup": CleanupScreen,
        "event-log": EventLogScreen,
        "reset-preview": ResetPreviewScreen,
        "settings": SettingsScreen,
        "help": HelpScreen,
    }

    BINDINGS = [
        *[
            Binding(str(info.number), f"switch_screen('{info.screen_id}')", info.label, priority=True)
            for info in SCREEN_INFOS
        ],
        Binding("?", "show_help", "Help", priority=True),
        Binding("q", "quit", "Quit", priority=True),
    ]

    def __init__(
        self,
        release_id: str | None = None,
        run_id: str | None = None,
        config_path: Path | None = None,
    ):
        super().__init__()
        self._release_id = release_id
        self._run_id = run_id
        self._config_path = config_path

    def on_mount(self) -> None:
        self.push_screen("dashboard")

    def action_show_help(self) -> None:
        screen_info = screen_info_for_class_name(self.screen.__class__.__name__)
        self.push_screen(HelpScreen(current_screen_info=screen_info))

    @property
    def release_id(self) -> str | None:
        return self._release_id

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def config_path(self) -> Path | None:
        return self._config_path
