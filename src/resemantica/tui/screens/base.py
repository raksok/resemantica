from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, cast

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from resemantica.observability.granularity import classify_event_level, tui_verbosity_to_level
from resemantica.orchestration.stop import StopToken
from resemantica.tui.launch_control import (
    LaunchContext,
    LaunchSnapshot,
    TuiSession,
    build_snapshot,
)
from resemantica.tui.navigation import format_footer_keys, format_location, screen_info_for_class_name

if TYPE_CHECKING:
    from resemantica.tracking.models import Event
    from resemantica.tui.app import ResemanticaApp

_UNSET = object()


@dataclass
class HeaderPassIndicator:
    label: str = "IDLE"
    color: str = "comment"
    running: bool = False
    stale: bool = False


@dataclass(frozen=True)
class StageProgress:
    total: int | None = None
    completed: int = 0
    active_chapter: int | None = None

    @property
    def has_progress(self) -> bool:
        return self.total is not None


class BaseScreen(Screen):
    _PULSE_WIDTH = 30
    _PULSE_GLYPHS = "▁▂▃▄▅▆▇█"
    _SPINNER_GLYPHS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    _REFRESH_INTERVAL_SECONDS = 2.0
    _SPINNER_INTERVAL_SECONDS = 0.25
    _STALE_AFTER_SECONDS = 300

    @property
    def app(self) -> "ResemanticaApp":
        return cast("ResemanticaApp", super().app)

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static(id="pulse-bar"),
            Static(id="header-screen-location"),
            Static(id="header-run-info"),
            Static(id="header-chapter-progress"),
            Static(id="header-pass"),
            id="header-container",
            classes="header-bar",
        )
        yield Vertical(
            Static("Chapter Spine", id="spine-title"),
            Vertical(id="spine-items"),
            id="spine-container",
            classes="spine",
        )
        with Container(id="main-content"):
            yield from self._content_widgets()
        yield Horizontal(
            Static(id="footer-block-progress"),
            Static(id="footer-warnings"),
            Static(id="footer-failures"),
            Static(id="footer-elapsed"),
            Static(id="footer-keys"),
            id="footer-container",
            classes="footer-bar",
        )

    def _content_widgets(self) -> ComposeResult:
        yield Static("")

    def on_mount(self) -> None:
        self._header_pass_indicator = HeaderPassIndicator()
        self._cached_run_state: dict[str, Any] | None = None
        self._cached_recent_events: list[Event] = []
        self._cached_chapter_count = 0
        self._cached_extraction_manifest_exists = False
        self._refresh_all()
        self.set_interval(self._REFRESH_INTERVAL_SECONDS, self._refresh_all)
        self.set_interval(self._SPINNER_INTERVAL_SECONDS, self._refresh_header_pass)

    def _refresh_all(self) -> None:
        if self._fast_refresh_active():
            fast_state = self._cached_run_state_for_refresh() or {}
            events = self._cached_recent_events_for_refresh()
            chapter_count = self._cached_chapter_count_for_refresh()
            self._update_header(state=fast_state, events=events, chapter_count=chapter_count)
            self._update_footer(state=fast_state, events=events)
            return

        state = self._get_run_state()
        events = self._load_recent_run_events()
        chapter_count = self._load_chapter_count()
        self._store_refresh_cache(
            state=state,
            events=events,
            chapter_count=chapter_count,
        )
        self._update_header(state=state, events=events, chapter_count=chapter_count)
        self._update_spine()
        self._update_footer(state=state, events=events)

    def _fast_refresh_active(self) -> bool:
        return getattr(self.app, "active_action", None) is not None

    def _store_refresh_cache(
        self,
        *,
        state: dict[str, Any] | None | object = _UNSET,
        events: list[Event] | object = _UNSET,
        chapter_count: int | object = _UNSET,
        extraction_manifest_exists: bool | object = _UNSET,
    ) -> None:
        if state is not _UNSET:
            self._cached_run_state = state if isinstance(state, dict) else None
        if isinstance(events, list):
            self._cached_recent_events = events
        if isinstance(chapter_count, int):
            self._cached_chapter_count = chapter_count
        if isinstance(extraction_manifest_exists, bool):
            self._cached_extraction_manifest_exists = extraction_manifest_exists

    def _cached_run_state_for_refresh(self) -> dict[str, Any] | None:
        return getattr(self, "_cached_run_state", None)

    def _cached_recent_events_for_refresh(self, *, limit: int = 5000) -> list[Event]:
        events = getattr(self, "_cached_recent_events", [])
        return events[:limit]

    def _recent_live_events_for_refresh(self, *, limit: int = 500) -> list[Event]:
        recent_live_events = getattr(self.app, "recent_live_events", None)
        if not callable(recent_live_events):
            return []
        return recent_live_events(limit=limit)

    def _combined_recent_events_for_refresh(
        self,
        persisted_events: list[Event],
        *,
        limit: int = 5000,
    ) -> list[Event]:
        live_events = self._recent_live_events_for_refresh()
        if not live_events:
            return persisted_events[:limit]

        events_by_id: dict[str, Event] = {}
        for event in [*persisted_events, *live_events]:
            events_by_id[event.event_id] = event

        def sort_key(event: Event) -> tuple[datetime, str]:
            parsed = self._parse_timestamp(event.event_time)
            return (parsed or datetime.min.replace(tzinfo=timezone.utc), event.event_id)

        return sorted(events_by_id.values(), key=sort_key, reverse=True)[:limit]

    def _cached_chapter_count_for_refresh(self) -> int:
        return getattr(self, "_cached_chapter_count", 0)

    def _cached_extraction_manifest_for_refresh(self) -> bool:
        return getattr(self, "_cached_extraction_manifest_exists", False)

    def _event_source_mode(self) -> str:
        return "summary_cached"

    def _default_event_filter(self, event: Event) -> bool:
        return True

    def _tui_event_level(self) -> int:
        return tui_verbosity_to_level(getattr(self.app, "observability_verbosity", "debug"))

    def _screen_events_for_tail(self, *, limit: int = 5000) -> list[Event]:
        events = self._recent_events_for_refresh(limit=limit)
        max_level = self._tui_event_level()
        return [
            event
            for event in events
            if classify_event_level(event) <= max_level and self._default_event_filter(event)
        ]

    def _run_state_for_refresh(self) -> dict[str, Any] | None:
        if self._fast_refresh_active():
            return self._cached_run_state_for_refresh()
        state = self._get_run_state()
        self._store_refresh_cache(state=state)
        return state

    def _recent_events_for_refresh(self, *, limit: int = 5000) -> list[Event]:
        if self._fast_refresh_active():
            return self._combined_recent_events_for_refresh(
                self._cached_recent_events_for_refresh(limit=limit),
                limit=limit,
            )
        events = self._load_recent_run_events(limit=limit)
        self._store_refresh_cache(events=events)
        return events

    def _extraction_manifest_for_refresh(self) -> bool:
        if self._fast_refresh_active():
            return self._cached_extraction_manifest_for_refresh()
        exists = self._check_extraction_manifest()
        self._store_refresh_cache(extraction_manifest_exists=exists)
        return exists

    def _get_release_id(self) -> str | None:
        try:
            app = self.app
        except Exception:
            return None
        return getattr(app, "release_id", None)

    def _get_run_id(self) -> str | None:
        try:
            app = self.app
        except Exception:
            return None
        return getattr(app, "run_id", None)

    def _update_header(
        self,
        *,
        state: dict[str, Any] | None = None,
        events: list[Event] | None = None,
        chapter_count: int | None = None,
    ) -> None:
        state = self._get_run_state() if state is None else state
        events = self._load_recent_run_events() if events is None else events
        chapter_count = self._load_chapter_count() if chapter_count is None else chapter_count

        pulse = self.query_one("#pulse-bar", Static)
        pulse.update(self._render_pulse_bar(state, events))

        screen_info = screen_info_for_class_name(self.__class__.__name__)
        screen_location = self.query_one("#header-screen-location", Static)
        screen_location.update(format_location(screen_info))

        run_id = self._get_run_id() or "--"
        release_id = self._get_release_id() or "--"
        run_info = self.query_one("#header-run-info", Static)
        run_info.update(f"Run: {run_id}  Rel: {release_id}")

        chapter_progress = self.query_one("#header-chapter-progress", Static)
        chapter_progress.update(
            self._format_chapter_progress(
                total_chapters=chapter_count,
                checkpoint=state["checkpoint"] if state else None,
            )
        )

        state_for_indicator = state
        active_action = getattr(self.app, "active_action", None)
        if active_action is not None and (
            not state_for_indicator or state_for_indicator.get("status") != "running"
        ):
            state_for_indicator = {
                **(state_for_indicator or {}),
                "stage_name": active_action,
                "status": "running",
            }

        pass_label, pass_color = self._derive_pass_indicator(state_for_indicator, events)
        self._header_pass_indicator = HeaderPassIndicator(
            label=pass_label,
            color=pass_color,
            running=bool(state_for_indicator and state_for_indicator.get("status") == "running"),
            stale=self._is_run_stale(state_for_indicator, events),
        )
        self._refresh_header_pass()

    def _refresh_live_progress(self) -> None:
        if not self._fast_refresh_active():
            return
        events = self._recent_events_for_refresh()
        state = self._cached_run_state_for_refresh() or {}
        chapter_count = self._cached_chapter_count_for_refresh()
        self._update_header(state=state, events=events, chapter_count=chapter_count)
        self._update_footer(state=state, events=events)

    def _refresh_header_pass(self) -> None:
        indicator = getattr(self, "_header_pass_indicator", HeaderPassIndicator())
        pass_widget = self.query_one_optional("#header-pass", Static)
        if pass_widget is None:
            return
        if indicator.stale:
            pass_widget.update("[orange]STALE[/]")
        elif indicator.running:
            pass_widget.update(
                f"[{indicator.color}]{self._spinner_frame()} {indicator.label}[/]"
            )
        else:
            pass_widget.update(f"[{indicator.color}]{indicator.label}[/]")

    def _update_spine(self) -> None:
        spine_items = self.query_one("#spine-items", Vertical)
        spine_items.remove_children()

        chapter_data = self._get_chapter_spine_data()
        if chapter_data:
            for label, css in self._render_spine_items(chapter_data):
                spine_items.mount(Static(label, classes=css))
        else:
            spine_items.mount(Static("[dim]No chapter data.[/]", classes="spine-item"))

    def _get_chapter_spine_data(self) -> list[tuple[int, str]]:
        release_id = self._get_release_id()
        if not release_id:
            return []
        try:
            from resemantica.chapters.manifest import list_extracted_chapters
            from resemantica.settings import derive_paths, load_config

            config = load_config(getattr(self.app, "config_path", None))
            paths = derive_paths(config, release_id=release_id)
            refs = list_extracted_chapters(paths)
            chapter_numbers = [ref.chapter_number for ref in refs]

            run_id = self._get_run_id()
            if run_id:
                statuses = self._load_chapter_statuses(release_id, run_id)
                return [(n, statuses.get(n, "not-started")) for n in chapter_numbers]
            return [(n, "not-started") for n in chapter_numbers]
        except Exception:
            return []

    def _load_chapter_statuses(self, release_id: str, run_id: str) -> dict[int, str]:
        from resemantica.tracking.repo import ensure_tracking_db, load_events

        conn = ensure_tracking_db(release_id)
        try:
            events = load_events(conn, run_id=run_id, release_id=release_id, limit=1000)
            statuses: dict[int, str] = {}
            for ev in reversed(events):
               if ev.chapter_number is None:
                   continue
               event_type = ev.event_type or ""
               if event_type.endswith(".chapter_completed"):
                   statuses[ev.chapter_number] = "complete"
               elif event_type.endswith(".chapter_started") and ev.chapter_number not in statuses:
                   statuses[ev.chapter_number] = "in-progress"
               elif ("fail" in event_type.lower() or event_type.endswith(".failed")) and ev.chapter_number not in statuses:
                   statuses[ev.chapter_number] = "failed"

            return statuses
        finally:
            conn.close()

    @staticmethod
    def _render_spine_items(chapter_data: list[tuple[int, str]]) -> list[tuple[str, str]]:
        STATUS_MAP: dict[str, tuple[str, str]] = {
            "not-started": ("□", "spine-status-not-started"),
            "in-progress": ("▸", "spine-status-in-progress"),
            "complete": ("■", "spine-status-complete"),
            "failed": ("✗", "spine-status-failed"),
            "high-risk": ("◈", "spine-status-high-risk"),
        }
        items: list[tuple[str, str]] = []
        for ch_num, status in chapter_data:
            char, css = STATUS_MAP.get(status, STATUS_MAP["not-started"])
            items.append((f"{char} Ch {ch_num}", f"spine-item {css}"))
        return items

    def _update_footer(
        self,
        *,
        state: dict[str, Any] | None = None,
        events: list[Event] | None = None,
    ) -> None:
        state = self._get_run_state() if state is None else state
        events = self._load_recent_run_events() if events is None else events

        footer_block_progress = self.query_one("#footer-block-progress", Static)
        footer_warnings = self.query_one("#footer-warnings", Static)
        footer_failures = self.query_one("#footer-failures", Static)
        footer_elapsed = self.query_one("#footer-elapsed", Static)

        metrics = self._derive_footer_metrics(state, events)
        footer_block_progress.update(metrics["block_progress"])
        footer_warnings.update(metrics["warnings"])
        footer_failures.update(metrics["failures"])
        footer_elapsed.update(metrics["elapsed"])

        footer_keys = self.query_one("#footer-keys", Static)
        keys = format_footer_keys(screen_info_for_class_name(self.__class__.__name__))
        if getattr(self.app, "active_action", None) is not None:
            if getattr(self.app, "active_stop_requested", False):
                keys = f"{keys}  [cyan]Stopping[/]"
            else:
                keys = f"{keys}  x Stop"
        footer_keys.update(keys)

    def _get_run_state(self) -> dict[str, Any] | None:
        run_id = self._get_run_id()
        release_id = self._get_release_id()
        if not run_id or not release_id:
            return None
        try:
            from resemantica.tracking.repo import ensure_tracking_db, load_run_state
            conn = ensure_tracking_db(release_id)
            try:
                state = load_run_state(conn, run_id)
                if state is None:
                    return None
                return {
                    "run_id": state.run_id,
                    "release_id": state.release_id,
                    "stage_name": state.stage_name,
                    "status": state.status,
                    "started_at": state.started_at,
                    "finished_at": state.finished_at,
                    "checkpoint": state.checkpoint,
                    "metadata": state.metadata,
                }
            finally:
                conn.close()
        except Exception:
            return None

    def _make_adapter(self):
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if not release_id or not run_id:
            return None
        from resemantica.tui.adapter import TUIAdapter

        return TUIAdapter(
            release_id=release_id,
            run_id=run_id,
            config_path=getattr(self.app, "config_path", None),
        )

    def _chapter_scope_options(self) -> dict[str, int]:
        session: TuiSession | None = getattr(self.app, "session", None)
        if session is None:
            return {}

        options: dict[str, int] = {}
        if session.chapter_start is not None:
            options["chapter_start"] = session.chapter_start
        if session.chapter_end is not None:
            options["chapter_end"] = session.chapter_end
        return options

    def _load_chapter_count(self) -> int:
        release_id = self._get_release_id()
        if not release_id:
            return 0
        try:
            from resemantica.chapters.manifest import list_extracted_chapters
            from resemantica.settings import derive_paths, load_config

            config = load_config(getattr(self.app, "config_path", None))
            paths = derive_paths(config, release_id=release_id)
            return len(list_extracted_chapters(paths))
        except Exception:
            return 0

    def _load_recent_run_events(self, *, limit: int = 5000) -> list[Event]:
        run_id = self._get_run_id()
        release_id = self._get_release_id()
        if not run_id or not release_id:
            return []
        try:
            from resemantica.tracking.repo import ensure_tracking_db, load_events

            conn = ensure_tracking_db(release_id)
            try:
                return load_events(conn, run_id=run_id, release_id=release_id, limit=limit)
            finally:
                conn.close()
        except Exception:
            return []

    @staticmethod
    def _event_matches_stage_prefix(event: Event, prefixes: tuple[str, ...]) -> bool:
        stage_name = (event.stage_name or "").lower()
        event_type = (event.event_type or "").lower()
        return any(
            stage_name.startswith(prefix) or event_type.startswith(prefix)
            for prefix in prefixes
        )

    @classmethod
    def _event_summary(cls, event: Event) -> str:
        severity = (event.severity or "info").lower()
        color = "red" if severity == "error" else "orange" if severity == "warning" else "comment"
        message = (event.message or "").strip() or event.event_type or "(event)"
        parts = [message]
        if event.chapter_number is not None:
            parts.append(f"ch={event.chapter_number}")
        if event.block_id:
            parts.append(f"block={event.block_id}")
        return f"  [{color}]{severity.upper()}:[/] {'  '.join(parts)[:104]}"

    @classmethod
    def _render_event_tail(
        cls,
        events: list[Event],
        *,
        title: str,
        limit: int = 5,
    ) -> str:
        events = cls._dedupe_event_tail_events(events)
        lines = [f"[bold]{title}[/bold]"]
        if not events:
            lines.append("  [dim]No recent events.[/]")
            return "\n".join(lines)
        for event in events[:limit]:
            lines.append(cls._event_summary(event))
        if len(events) > limit:
            lines.append(f"  [dim]+{len(events) - limit} more[/]")
        return "\n".join(lines)

    def _event_tail_limit(self, widget_id: str, *, minimum: int = 5) -> int:
        widget = self.query_one_optional(widget_id, Static)
        if widget is None:
            return minimum

        height = 0
        try:
            height = int(widget.region.height)
        except Exception:
            height = 0
        if height <= 0:
            try:
                height = int(widget.size.height)
            except Exception:
                height = 0

        if height <= 0:
            return minimum

        # Reserve a small amount of space for the title line and the border chrome.
        return max(minimum, height - 3)

    @classmethod
    def _dedupe_event_tail_events(cls, events: list[Event]) -> list[Event]:
        deduped: list[Event] = []
        seen_ids: set[str] = set()
        seen_signatures: set[tuple[object, ...]] = set()
        for event in events:
            if event.event_id in seen_ids:
                continue
            signature = cls._event_tail_signature(event)
            if signature in seen_signatures:
                continue
            seen_ids.add(event.event_id)
            seen_signatures.add(signature)
            deduped.append(event)
        return deduped

    @staticmethod
    def _event_tail_signature(event: Event) -> tuple[object, ...]:
        return (
            event.run_id,
            event.release_id,
            event.event_type,
            event.stage_name,
            event.chapter_number,
            event.block_id,
            event.severity,
            event.message,
            repr(sorted(event.payload.items())),
        )

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
        return None

    @classmethod
    def _chapter_index_from_checkpoint(cls, checkpoint: dict[str, Any] | None) -> int:
        if not isinstance(checkpoint, dict):
            return 0

        chapter_number = cls._coerce_int(checkpoint.get("chapter_number"))
        if chapter_number is not None:
            return max(0, chapter_number)

        max_completed = 0
        for key in (
            "completed_chapters",
            "pass1_completed",
            "pass2_completed",
            "pass3_completed",
        ):
            values = checkpoint.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                parsed = cls._coerce_int(item)
                if parsed is not None:
                    max_completed = max(max_completed, parsed)
        return max_completed

    @classmethod
    def _format_chapter_progress(
        cls,
        *,
        total_chapters: int,
        checkpoint: dict[str, Any] | None,
    ) -> str:
        current = cls._chapter_index_from_checkpoint(checkpoint)
        return f"Ch {current}/{max(0, total_chapters)}"

    @staticmethod
    def _event_type_matches(event_type: str, suffix: str) -> bool:
        lowered = event_type.lower()
        target = suffix.lower()
        return lowered == target or lowered.endswith(f".{target}")

    @classmethod
    def _derive_pass_indicator(
        cls,
        state: dict[str, Any] | None,
        events: list[Event],
    ) -> tuple[str, str]:
        if not state or state.get("status") != "running":
            return ("IDLE", "comment")

        stage_name = str(state.get("stage_name") or "").lower()
        if stage_name == "epub-extract":
            return ("EXTRACT", "cyan")
        if stage_name == "epub-rebuild":
            return ("REBUILD", "green")
        if stage_name.startswith("preprocess-") or stage_name == "packets-build":
            return ("PREPROCESS", "comment")

        hints = [stage_name, str(state.get("checkpoint") or "").lower()]
        for event in events[:25]:
            hints.extend(
                [
                    event.stage_name.lower(),
                    event.event_type.lower(),
                    event.message.lower(),
                    str(event.payload).lower(),
                ]
            )
        combined = " ".join(hints)

        if stage_name in {"translate-range", "translate-chapter"}:
            if "pass3" in combined:
                return ("PASS 3", "cyan")
            if "pass2" in combined:
                return ("PASS 2", "cyan")
            return ("PASS 1", "cyan")

        return ("RUNNING", "cyan")

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _latest_event_time(cls, events: list[Event]) -> datetime | None:
        parsed_events = [
            parsed
            for event in events
            if (parsed := cls._parse_timestamp(event.event_time)) is not None
        ]
        return max(parsed_events) if parsed_events else None

    @classmethod
    def _is_run_stale(
        cls,
        state: dict[str, Any] | None,
        events: list[Event],
        *,
        now: datetime | None = None,
    ) -> bool:
        if not state or state.get("status") != "running":
            return False

        from resemantica.tui.launch_control import is_stale

        started_at = state.get("started_at")
        latest_event_time = cls._latest_event_time(events)
        timestamp = latest_event_time.isoformat() if latest_event_time else started_at
        return is_stale(timestamp, now=now, timeout_seconds=cls._STALE_AFTER_SECONDS)

    def _build_launch_context(self) -> LaunchContext:
        session: TuiSession | None = getattr(self.app, "session", None)
        return LaunchContext(
            release_id=self._get_release_id(),
            run_id=self._get_run_id(),
            input_path=session.input_path if session else None,
            chapter_start=session.chapter_start if session else None,
            chapter_end=session.chapter_end if session else None,
        )

    def _check_extraction_manifest(self) -> bool:
        release_id = self._get_release_id()
        if not release_id:
            return False
        try:
            from resemantica.chapters.manifest import list_extracted_chapters
            from resemantica.settings import derive_paths, load_config

            config = load_config(getattr(self.app, "config_path", None))
            paths = derive_paths(config, release_id=release_id)
            refs = list_extracted_chapters(paths)
            return len(refs) > 0
        except Exception:
            return False

    def _build_snapshot(
        self,
        events: list[Event] | None = None,
        run_state: dict | None = None,
    ) -> LaunchSnapshot:
        if events is None:
            events = self._recent_events_for_refresh()
        if run_state is None:
            run_state = self._run_state_for_refresh()
        return build_snapshot(
            context=self._build_launch_context(),
            active_action=getattr(self.app, "active_action", None),
            run_state=run_state,
            events=events,
            extraction_manifest_exists=self._extraction_manifest_for_refresh(),
        )

    def start_worker(self, action_key: str, adapter_method: Callable[..., Any]) -> None:
        if getattr(self.app, "active_action", None) is not None:
            self.notify("Another action is already running", severity="warning", timeout=3)
            return
        clear_live_events = getattr(self.app, "clear_live_events", None)
        if callable(clear_live_events):
            clear_live_events()
        stop_token = StopToken()
        self.app.active_action = action_key
        self.app.active_stop_token = stop_token
        self.app.active_stop_requested = False
        self._run_worker(action_key, adapter_method, stop_token)

    @work(thread=True)
    async def _run_worker(
        self,
        action_key: str,
        adapter_method: Callable[..., Any],
        stop_token: StopToken,
    ) -> None:
        try:
            result = adapter_method(stop_token)
            self.app.call_from_thread(self._on_worker_success, action_key, result)
        except Exception as exc:
            self.app.call_from_thread(self._on_worker_failure, action_key, str(exc))

    def _on_worker_success(self, action_key: str, result: Any) -> None:
        self.app.active_action = None
        self.app.active_stop_token = None
        self.app.active_stop_requested = False
        self._refresh_all()

    def _on_worker_failure(self, action_key: str, exc: Exception) -> None:
        self.app.active_action = None
        self.app.active_stop_token = None
        self.app.active_stop_requested = False

        self.notify(f"Launch failed: {exc}", severity="error", timeout=5)
        self._refresh_all()

    @classmethod
    def _format_activity_age(
        cls,
        state: dict[str, Any] | None,
        events: list[Event],
        *,
        now: datetime | None = None,
    ) -> str:
        latest_event_time = cls._latest_event_time(events)
        if latest_event_time is None and state:
            latest_event_time = cls._parse_timestamp(state.get("started_at"))
        if latest_event_time is None:
            return "no events yet"

        current_time = now or datetime.now(timezone.utc)
        total_seconds = max(0, int((current_time - latest_event_time).total_seconds()))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m ago"
        if minutes:
            return f"{minutes}m {seconds}s ago"
        return f"{seconds}s ago"

    @classmethod
    def _format_status_label(
        cls,
        state: dict[str, Any] | None,
        events: list[Event],
        *,
        now: datetime | None = None,
    ) -> str:
        if not state:
            return "[dim]NO ACTIVE RUN[/]"

        status = str(state.get("status") or "unknown").upper()
        if cls._is_run_stale(state, events, now=now):
            age = cls._format_activity_age(state, events, now=now)
            return f"[orange]STALE[/] ([dim]last event {age}[/])"
        if status == "RUNNING":
            return f"[cyan]{cls._spinner_frame(now=now)} RUNNING[/]"
        if status == "FAILED":
            return "[red]FAILED[/]"
        if status == "COMPLETED":
            return "[green]COMPLETED[/]"
        return f"[comment]{status}[/]"

    @classmethod
    def _derive_stage_progress(cls, events: list[Any]) -> dict[str, StageProgress]:
        deduped: dict[str, Any] = {}
        for event in events:
            event_id = str(getattr(event, "event_id", ""))
            if not event_id:
                event_id = repr(
                    (
                        getattr(event, "event_time", ""),
                        getattr(event, "event_type", ""),
                        getattr(event, "chapter_number", None),
                    )
                )
            deduped[event_id] = event

        ordered = sorted(
            deduped.values(),
            key=lambda event: (str(getattr(event, "event_time", "")), str(getattr(event, "event_id", ""))),
        )
        totals: dict[str, int] = {}
        completed: dict[str, set[int]] = {}
        active: dict[str, int] = {}

        for event in ordered:
            event_type = str(getattr(event, "event_type", "") or "")
            payload = getattr(event, "payload", {}) or {}
            total = payload.get("total_chapters") if isinstance(payload, dict) else None
            if event_type.endswith(".started"):
                stage_key = event_type.removesuffix(".started")
                if isinstance(total, int):
                    totals[stage_key] = total
                continue

            if event_type.endswith(".chapter_started"):
                stage_key = event_type.removesuffix(".chapter_started")
                chapter_number = getattr(event, "chapter_number", None)
                if isinstance(chapter_number, int):
                    active[stage_key] = chapter_number
                continue

            if event_type.endswith(".chapter_completed") or event_type.endswith(".chapter_skipped"):
                stage_key = event_type.rsplit(".", 1)[0]
                chapter_number = getattr(event, "chapter_number", None)
                if isinstance(chapter_number, int):
                    completed.setdefault(stage_key, set()).add(chapter_number)
                    if active.get(stage_key) == chapter_number:
                        active.pop(stage_key, None)
                continue

        models: dict[str, StageProgress] = {}
        for stage_key, total in totals.items():
            done = completed.get(stage_key, set())
            models[stage_key] = StageProgress(
                total=total,
                completed=min(len(done), total),
                active_chapter=active.get(stage_key),
            )
        return models

    @staticmethod
    def _render_scoped_bar(model: StageProgress, status: str) -> str:
        width = 20
        total = max(1, model.total or 0)
        completed = min(max(0, model.completed), total)
        if completed >= total:
            return "[green]\u2501" + "\u2501" * (width - 1) + "[/]"
        filled = int((completed / total) * width)
        has_active = model.active_chapter is not None or status == "running"
        marker = "\u257a" if has_active else "\u2500"
        empty = max(0, width - filled - (1 if has_active else 0))
        color = "cyan" if status == "running" or has_active else "comment"
        filled_text = "\u2501" * filled
        marker_text = marker if has_active else ""
        empty_text = "\u2500" * empty
        return f"[{color}]{filled_text}{marker_text}{empty_text}[/]"

    @staticmethod
    def _static_bar(*, color: str, fill: str, width: int = 20) -> str:
        return f"[{color}]{fill * width}[/]"

    @staticmethod
    def _running_bar(*, color: str, width: int = 20) -> str:
        filled = "\u2501" * 8
        marker = "\u257a"
        remaining = "\u2500" * (width - len(filled) - 1)
        return f"[{color}]{filled}{marker}{remaining}[/]"

    @classmethod
    def _spinner_frame(cls, *, now: datetime | None = None) -> str:
        current_time = now or datetime.now(timezone.utc)
        index = int(current_time.timestamp() * 4) % len(cls._SPINNER_GLYPHS)
        return cls._SPINNER_GLYPHS[index]

    @classmethod
    def _bucket_index(
        cls,
        event_time: datetime,
        *,
        start: datetime,
        end: datetime,
    ) -> int:
        duration = max((end - start).total_seconds(), 1.0)
        offset = min(max((event_time - start).total_seconds(), 0.0), duration)
        position = offset / duration
        return min(cls._PULSE_WIDTH - 1, int(position * cls._PULSE_WIDTH))

    @classmethod
    def _render_pulse_bar(
        cls,
        state: dict[str, Any] | None,
        events: list[Event],
        *,
        now: datetime | None = None,
    ) -> str:
        idle = cls._PULSE_GLYPHS[0] * cls._PULSE_WIDTH
        if not state or state.get("status") != "running":
            return f"[comment]{idle}[/]"
        if cls._is_run_stale(state, events, now=now):
            return f"[orange]{idle}[/]"

        current_time = now or datetime.now(timezone.utc)
        started_at = cls._parse_timestamp(state.get("started_at")) or current_time
        finished_at = cls._parse_timestamp(state.get("finished_at")) or current_time
        if finished_at <= started_at:
            finished_at = started_at + timedelta(seconds=1)

        paragraph_events = [
            event
            for event in events
            if cls._event_type_matches(event.event_type, "paragraph_completed")
        ]
        retry_events = [
            event
            for event in events
            if "retry" in event.event_type.lower()
        ]
        if not paragraph_events and not retry_events:
            return f"[comment]{idle}[/]"

        buckets = [0] * cls._PULSE_WIDTH
        for event in paragraph_events:
            event_time = cls._parse_timestamp(event.event_time)
            if event_time is None:
                continue
            buckets[cls._bucket_index(event_time, start=started_at, end=finished_at)] += 1

        max_bucket = max(buckets, default=0)
        if max_bucket <= 0:
            sparkline = idle
        else:
            chars: list[str] = []
            for count in buckets:
                if count <= 0:
                    chars.append(cls._PULSE_GLYPHS[0])
                    continue
                level = max(1, math.ceil((count / max_bucket) * (len(cls._PULSE_GLYPHS) - 1)))
                chars.append(cls._PULSE_GLYPHS[level])
            sparkline = "".join(chars)

        has_retry_spike = any(
            cls._parse_timestamp(event.event_time) is not None
            for event in retry_events
        )
        color = "red" if has_retry_spike else "cyan"
        return f"[{color}]{sparkline}[/]"

    @classmethod
    def _derive_footer_metrics(
        cls,
        state: dict[str, Any] | None,
        events: list[Event],
        *,
        now: datetime | None = None,
    ) -> dict[str, str]:
        completed_blocks: set[str] = set()
        seen_blocks: set[str] = set()

        for event in events:
            if not event.block_id:
                continue
            event_type = event.event_type.lower()
            if ".paragraph_" not in event_type and "paragraph_" not in event_type and "block" not in event_type:
                continue
            seen_blocks.add(event.block_id)
            if cls._event_type_matches(event.event_type, "paragraph_completed"):
                completed_blocks.add(event.block_id)

        warnings = sum(1 for event in events if event.severity == "warning")
        failures = sum(1 for event in events if event.severity == "error")
        elapsed = cls._format_elapsed(state, now=now)
        return {
            "block_progress": f"{len(completed_blocks)}/{len(seen_blocks)} blocks",
            "warnings": f"Warn {warnings}",
            "failures": f"Fail {failures}",
            "elapsed": elapsed,
        }

    @classmethod
    def _format_elapsed(
        cls,
        state: dict[str, Any] | None,
        *,
        now: datetime | None = None,
    ) -> str:
        if not state:
            return "0:00:00"

        started_at = cls._parse_timestamp(state.get("started_at"))
        if started_at is None:
            return "0:00:00"

        current_time = now or datetime.now(timezone.utc)
        finished_at = cls._parse_timestamp(state.get("finished_at")) or current_time
        elapsed_seconds = max(0, int((finished_at - started_at).total_seconds()))
        hours, remainder = divmod(elapsed_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"
