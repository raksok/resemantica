from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static

from resemantica.tui.screens.base import BaseScreen


class IngestionScreen(BaseScreen):
    BINDINGS = [
        Binding("e", "launch_extract", "Extract"),
    ]

    def _content_widgets(self) -> ComposeResult:
        with Container(id="ingestion-content"):
            yield Static("Ingestion / Extraction", classes="app-title")
            yield Static("", id="ingestion-path")
            yield Static("", id="ingestion-status")
            yield Static("", id="ingestion-chapter-list")
            yield Static("", id="ingestion-event-tail", classes="event-tail")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_ingestion()

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._refresh_ingestion()

    def _refresh_ingestion(self) -> None:
        session = getattr(self.app, "session", None)
        input_path = session.input_path if session else None

        path_widget = self.query_one("#ingestion-path", Static)
        if input_path:
            path_widget.update(f"[bold]EPUB:[/] {input_path}")
        else:
            path_widget.update("[dim]No EPUB path set — use Dashboard to enter one.[/]")

        snapshot = self._build_snapshot()
        status_widget = self.query_one("#ingestion-status", Static)
        parts: list[str] = []

        for stage in snapshot.stages:
            if stage.key != "epub-extract":
                continue
            color = {
                "missing": "comment",
                "ready": "green",
                "running": "cyan",
                "done": "green",
                "failed": "red",
                "blocked": "orange",
                "stale": "orange",
                "disabled": "dim",
            }.get(stage.status, "comment")
            status_text = stage.status.upper()
            hint = f"[bold]Extraction:[/] [{color}]{status_text}[/]"
            if stage.action.reason:
                hint += f" [dim]({stage.action.reason})[/]"
            parts.append(hint)
            break

        if snapshot.active_action == "epub-extract":
            parts.append(f"[cyan]{self._spinner_frame()} Extracting...[/]")
        if snapshot.latest_failure:
            parts.append(f"[red]Latest failure: {snapshot.latest_failure}[/]")

        if parts:
            parts.append("")
        parts.append("[dim]e[/]=Extract")
        status_widget.update("\n".join(parts))

        chapter_widget = self.query_one("#ingestion-chapter-list", Static)
        if self._check_extraction_manifest():
            try:
                from resemantica.chapters.manifest import list_extracted_chapters
                from resemantica.settings import derive_paths, load_config

                release_id = self._get_release_id()
                if release_id:
                    config = load_config(getattr(self.app, "config_path", None))
                    paths = derive_paths(config, release_id=release_id)
                    refs = list_extracted_chapters(paths)
                    lines = [f"[bold]Extracted Chapters ({len(refs)}):[/bold]"]
                    for ref in refs:
                        name = (ref.source_document_path or ref.chapter_path.name).replace(".xhtml", "")
                        lines.append(f"  Ch {ref.chapter_number}  {name}")
                    chapter_widget.update("\n".join(lines))
                    self._update_event_tail()
                    return
            except Exception:
                pass
            chapter_widget.update("[dim]Chapters extracted, but manifest could not be read.[/]")
        else:
            chapter_widget.update("")

        self._update_event_tail()

    def _update_event_tail(self) -> None:
        events = [
            event
            for event in self._load_recent_run_events()
            if self._event_matches_stage_prefix(event, ("epub-extract",))
        ]
        self.query_one("#ingestion-event-tail", Static).update(
            self._render_event_tail(events, title="Extraction Events")
        )

    def action_launch_extract(self) -> None:
        session = getattr(self.app, "session", None)
        input_path = session.input_path if session else None
        if not input_path:
            self.notify("No EPUB path selected — set one on Dashboard first", severity="error", timeout=3)
            return

        adapter = self._make_adapter()
        if adapter is None:
            self.notify("Cannot launch: release/run not set", severity="error", timeout=3)
            return

        resolved = Path(input_path).expanduser().resolve()
        self.start_worker("epub-extract", lambda: adapter.extract_epub(resolved))
