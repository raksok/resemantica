from __future__ import annotations

from pathlib import Path

from textual import events
from textual.app import App
from textual.binding import Binding

from resemantica.tui.launch_control import TuiSession
from resemantica.tui.navigation import SCREEN_INFOS, screen_info_for_class_name
from resemantica.tui.screens import (
    ArtifactScreen,
    DashboardScreen,
    HelpScreen,
    IngestionScreen,
    ObservabilityScreen,
    PreprocessingScreen,
    SettingsScreen,
    TranslationScreen,
)


class ResemanticaApp(App):
    TITLE = "Resemantica"
    SUB_TITLE = "Translation Pipeline"
    CSS_PATH = "palenight.tcss"

    SCREENS = {
        "dashboard": DashboardScreen,
        "ingestion": IngestionScreen,
        "preprocessing": PreprocessingScreen,
        "translation": TranslationScreen,
        "observability": ObservabilityScreen,
        "artifact": ArtifactScreen,
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
        self.active_action: str | None = None
        self.session = TuiSession()
        self._screen_bindings = {
            str(info.number): info.screen_id for info in SCREEN_INFOS
        }

    def on_mount(self) -> None:
        self.push_screen("dashboard")

    async def on_event(self, event: events.Event) -> None:
        if isinstance(event, events.Key):
            if event.key in ("?", "question_mark"):
                await self.action_show_help()
                event.stop()
                return
            if event.key == "q":
                focused = self.screen.focused
                if focused is None or focused.__class__.__name__ != "Input":
                    await self.action_quit()
                    event.stop()
                    return
            if event.key in self._screen_bindings:
                focused = self.screen.focused
                if focused is None or focused.__class__.__name__ != "Input":
                    screen_id = self._screen_bindings[event.key]
                    await self.action_switch_screen(screen_id)
                    event.stop()
                    return
            ctrl_key = event.key.startswith("ctrl+") and event.key[5:] in self._screen_bindings
            if ctrl_key:
                screen_id = self._screen_bindings[event.key[5:]]
                await self.action_switch_screen(screen_id)
                event.stop()
                return
        await super().on_event(event)

    async def action_show_help(self) -> None:
        screen_info = screen_info_for_class_name(self.screen.__class__.__name__)
        await self.push_screen(HelpScreen(current_screen_info=screen_info))

    @property
    def release_id(self) -> str | None:
        return self._release_id

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def config_path(self) -> Path | None:
        return self._config_path
