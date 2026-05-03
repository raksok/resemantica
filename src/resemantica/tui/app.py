from __future__ import annotations

from collections import deque
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from textual import events
from textual.app import App
from textual.binding import Binding

from resemantica.orchestration.stop import StopToken
from resemantica.tui.launch_control import TuiSession
from resemantica.tui.navigation import SCREEN_INFOS, screen_info_for_class_name
from resemantica.tui.observability import ObservabilityVerbosity
from resemantica.tui.screens import (
    ArtifactScreen,
    CleanupWizardScreen,
    DashboardScreen,
    HelpScreen,
    IngestionScreen,
    ObservabilityScreen,
    PreprocessingScreen,
    SettingsScreen,
    TranslationScreen,
)

if TYPE_CHECKING:
    from resemantica.tracking.models import Event


class ResemanticaApp(App):
    TITLE = "Resemantica"
    SUB_TITLE = "Translation Pipeline"
    CSS_PATH = "palenight.tcss"
    LIVE_PENDING_LIMIT = 1000
    LIVE_RETAINED_LIMIT = 500
    LIVE_REFRESH_INTERVAL_SECONDS = 0.25

    SCREENS = {
        "dashboard": DashboardScreen,
        "ingestion": IngestionScreen,
        "preprocessing": PreprocessingScreen,
        "translation": TranslationScreen,
        "observability": ObservabilityScreen,
        "artifact": ArtifactScreen,
        "cleanup-wizard": CleanupWizardScreen,
        "settings": SettingsScreen,
        "help": HelpScreen,
    }

    BINDINGS = [
        *[
            Binding(str(info.number), f"switch_screen('{info.screen_id}')", info.label, priority=True)
            for info in SCREEN_INFOS
        ],
        Binding("?", "show_help", "Help", priority=True),
        Binding("x", "request_stop", "Stop", priority=True, show=False),
        Binding("q", "quit", "Quit", priority=True),
    ]

    def __init__(
        self,
        release_id: str | None = None,
        run_id: str | None = None,
        config_path: Path | None = None,
        chapter_start: int | None = None,
        chapter_end: int | None = None,
    ):
        super().__init__()
        self._release_id = release_id
        self._run_id = run_id
        self._config_path = config_path
        self.active_action: str | None = None
        self.active_stop_token: StopToken | None = None
        self.active_stop_requested = False
        self.session = TuiSession(
            chapter_start=chapter_start,
            chapter_end=chapter_end,
        )
        self._screen_bindings = {
            str(info.number): info.screen_id for info in SCREEN_INFOS
        }
        self._live_pending_events: deque[Event] = deque(maxlen=self.LIVE_PENDING_LIMIT)
        self._live_events: deque[Event] = deque(maxlen=self.LIVE_RETAINED_LIMIT)
        self._live_event_lock = Lock()
        self._live_events_subscribed = False
        self.observability_verbosity: ObservabilityVerbosity = "debug"

    def on_mount(self) -> None:
        self._subscribe_live_events()
        self.push_screen("dashboard")
        self.set_interval(self.LIVE_REFRESH_INTERVAL_SECONDS, self._drain_live_events)

    def on_unmount(self) -> None:
        self._unsubscribe_live_events()

    def _subscribe_live_events(self) -> None:
        if self._live_events_subscribed:
            return
        from resemantica.orchestration.events import subscribe

        subscribe("*", self._on_live_event)
        self._live_events_subscribed = True

    def _unsubscribe_live_events(self) -> None:
        if not self._live_events_subscribed:
            return
        from resemantica.orchestration.events import unsubscribe

        unsubscribe("*", self._on_live_event)
        self._live_events_subscribed = False

    def _on_live_event(self, event: Event) -> None:
        if not self._live_event_matches(event):
            return
        with self._live_event_lock:
            self._live_pending_events.append(event)

    def _live_event_matches(self, event: Event) -> bool:
        if self.active_action is None:
            return False
        if self._run_id and event.run_id != self._run_id:
            return False
        if self._release_id and event.release_id != self._release_id:
            return False
        return True

    def _drain_live_events(self) -> None:
        pending: list[Event] = []
        with self._live_event_lock:
            if self._live_pending_events:
                pending = list(self._live_pending_events)
                self._live_pending_events.clear()
                self._live_events.extend(pending)

        if self.active_action is None:
            return

        from resemantica.tui.screens.base import (
            BlockUpdated,
            ChapterCompleted,
            ChapterHighRisk,
            ChapterStarted,
        )

        for event in pending:
            et = event.event_type
            ch = event.chapter_number
            if ch is not None:
                if et.endswith(".chapter_started"):
                    self.screen.post_message(ChapterStarted(event.stage_name, ch))
                elif et.endswith(".chapter_completed"):
                    self.screen.post_message(ChapterCompleted(event.stage_name, ch))
                elif et.endswith(".paragraph_skipped"):
                    payload = event.payload or {}
                    if isinstance(payload, dict) and payload.get("pass_name") == "pass3":
                        self.screen.post_message(ChapterHighRisk(event.stage_name, ch))
                elif et.endswith(".paragraph_started"):
                    self.screen.post_message(BlockUpdated(ch, event.block_id or "?", "in-progress"))
                elif et.endswith(".paragraph_completed"):
                    self.screen.post_message(BlockUpdated(ch, event.block_id or "?", "done"))
                elif et.endswith(".validation_failed") or et.endswith(".failed"):
                    if event.block_id:
                        self.screen.post_message(BlockUpdated(ch, event.block_id, "failed"))

        refresh_live = getattr(self.screen, "_refresh_live_progress", None)
        if callable(refresh_live):
            refresh_live()

    def recent_live_events(self, *, limit: int = LIVE_RETAINED_LIMIT) -> list[Event]:
        with self._live_event_lock:
            events = list(self._live_events)
        return list(reversed(events))[:limit]

    def clear_live_events(self) -> None:
        with self._live_event_lock:
            self._live_pending_events.clear()
            self._live_events.clear()

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
            if event.key == "x":
                focused = self.screen.focused
                if focused is None or focused.__class__.__name__ != "Input":
                    self.action_request_stop()
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

    async def action_switch_screen(self, screen_id: str) -> None:
        await self.push_screen(screen_id)
        render_tab_bar = getattr(self.screen, "_render_tab_bar", None)
        if callable(render_tab_bar):
            render_tab_bar()

    def action_request_stop(self) -> None:
        token = self.active_stop_token
        if self.active_action is None or token is None:
            return
        token.request_stop()
        self.active_stop_requested = True
        refresh_live = getattr(self.screen, "_refresh_live_progress", None)
        if callable(refresh_live):
            refresh_live()

    def set_ids(self, release_id: str, run_id: str) -> None:
        self._release_id = release_id
        self._run_id = run_id
        self.clear_live_events()

    @property
    def release_id(self) -> str | None:
        return self._release_id

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def config_path(self) -> Path | None:
        return self._config_path
