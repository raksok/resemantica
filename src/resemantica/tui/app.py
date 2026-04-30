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
)


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
    }

    BINDINGS = [
        Binding("1", "switch_screen('dashboard')", "Dashboard", priority=True),
        Binding("2", "switch_screen('preprocessing')", "Preprocess", priority=True),
        Binding("3", "switch_screen('translation')", "Translate", priority=True),
        Binding("4", "switch_screen('warnings')", "Warnings", priority=True),
        Binding("5", "switch_screen('artifacts')", "Artifacts", priority=True),
        Binding("6", "switch_screen('cleanup')", "Cleanup", priority=True),
        Binding("7", "switch_screen('event-log')", "Events", priority=True),
        Binding("8", "switch_screen('reset-preview')", "Reset", priority=True),
        Binding("9", "switch_screen('settings')", "Settings", priority=True),
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

    @property
    def release_id(self) -> str | None:
        return self._release_id

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def config_path(self) -> Path | None:
        return self._config_path
