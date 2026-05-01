from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import TYPE_CHECKING, Any, Callable

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from resemantica.tui.launch_control import (
    LaunchContext,
    LaunchSnapshot,
    TuiSession,
    build_snapshot,
)
from resemantica.tui.navigation import format_footer_keys, format_location, screen_info_for_class_name

if TYPE_CHECKING:
    from resemantica.tracking.models import Event


@dataclass
class HeaderPassIndicator:
    label: str = "IDLE"
    color: str = "comment"
    running: bool = False
    stale: bool = False


class BaseScreen(Screen):
    _PULSE_WIDTH = 30
    _PULSE_GLYPHS = "▁▂▃▄▅▆▇█"
    _SPINNER_GLYPHS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    _REFRESH_INTERVAL_SECONDS = 2.0
    _SPINNER_INTERVAL_SECONDS = 0.25
    _STALE_AFTER_SECONDS = 300

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
        self._refresh_all()
        self.set_interval(self._REFRESH_INTERVAL_SECONDS, self._refresh_all)
        self.set_interval(self._SPINNER_INTERVAL_SECONDS, self._refresh_header_pass)

    def _refresh_all(self) -> None:
        state = self._get_run_state()
        events = self._load_recent_run_events()
        chapter_count = self._load_chapter_count()
        self._update_header(state=state, events=events, chapter_count=chapter_count)
        self._update_spine()
        self._update_footer(state=state, events=events)

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

        pass_label, pass_color = self._derive_pass_indicator(state, events)
        self._header_pass_indicator = HeaderPassIndicator(
            label=pass_label,
            color=pass_color,
            running=bool(state and state.get("status") == "running"),
            stale=self._is_run_stale(state, events),
        )
        self._refresh_header_pass()

    def _refresh_header_pass(self) -> None:
        indicator = getattr(self, "_header_pass_indicator", HeaderPassIndicator())
        pass_widget = self.query_one("#header-pass", Static)
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
            from resemantica.settings import derive_paths, load_config
            from resemantica.chapters.manifest import list_extracted_chapters

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
                if ev.event_type == "chapter_completed":
                    statuses[ev.chapter_number] = "complete"
                elif ev.event_type == "chapter_started" and ev.chapter_number not in statuses:
                    statuses[ev.chapter_number] = "in-progress"
                elif "fail" in (ev.event_type or "").lower() and ev.chapter_number not in statuses:
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
        footer_keys.update(format_footer_keys(screen_info_for_class_name(self.__class__.__name__)))

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

        return ("IDLE", "comment")

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
            events = self._load_recent_run_events()
        if run_state is None:
            run_state = self._get_run_state()
        return build_snapshot(
            context=self._build_launch_context(),
            active_action=getattr(self.app, "active_action", None),
            run_state=run_state,
            events=events,
            extraction_manifest_exists=self._check_extraction_manifest(),
        )

    def start_worker(self, action_key: str, adapter_method: Callable[[], Any]) -> None:
        if getattr(self.app, "active_action", None) is not None:
            self.notify("Another action is already running", severity="warning", timeout=3)
            return
        self.app.active_action = action_key  # type: ignore[attr-defined]
        self._run_worker(action_key, adapter_method)

    @work(thread=True)
    async def _run_worker(self, action_key: str, adapter_method: Callable[[], Any]) -> None:
        try:
            result = adapter_method()
            self.app.call_from_thread(self._on_worker_success, action_key, result)
        except Exception as exc:
            self.app.call_from_thread(self._on_worker_failure, action_key, str(exc))

    def _on_worker_success(self, action_key: str, result: Any) -> None:
        self.app.active_action = None  # type: ignore[attr-defined]
        self._refresh_all()

    def _on_worker_failure(self, action_key: str, error: str) -> None:
        self.app.active_action = None  # type: ignore[attr-defined]
        self.notify(f"Launch failed: {error}", severity="error", timeout=5)
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
