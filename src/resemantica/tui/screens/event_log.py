from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from resemantica.orchestration.events import subscribe, unsubscribe
from resemantica.tracking.models import Event
from resemantica.tui.screens.base import BaseScreen


class EventLogScreen(BaseScreen):
    def _content_widgets(self) -> ComposeResult:
        with Container(id="event-log-content"):
            yield Static("Event Log", classes="app-title")
            yield Static("", id="event-log")

    def on_mount(self) -> None:
        super().on_mount()
        self._events: list[Event] = []
        subscribe("*", self._on_event)

    def on_unmount(self) -> None:
        unsubscribe("*", self._on_event)

    def _on_event(self, event: Event) -> None:
        if event.release_id != self._get_release_id() or event.run_id != self._get_run_id():
            return
        self._events.insert(0, event)
        self._events = self._events[:100]
        self.app.call_from_thread(self._render_events)

    def _render_events(self) -> None:
        target = self.query_one("#event-log", Static)
        lines = []
        for event in self._events[:30]:
            chapter = f" ch={event.chapter_number}" if event.chapter_number is not None else ""
            block = f" block={event.block_id}" if event.block_id else ""
            lines.append(
                f"[{event.severity}] {event.event_type}{chapter}{block}: {event.message}"
            )
        target.update("\n".join(lines) if lines else "[dim]No live events yet.[/]")
