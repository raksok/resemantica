from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


@dataclass(frozen=True)
class NewFileResult:
    input_path: Path
    release_id: str
    run_id: str
    chapter_start: int | None = None
    chapter_end: int | None = None


@dataclass(frozen=True)
class ResumeRunResult:
    input_path: Path | None
    release_id: str
    run_id: str
    chapter_start: int | None = None
    chapter_end: int | None = None


def parse_chapter_bounds(
    raw_start: str,
    raw_end: str,
) -> tuple[int | None, int | None, str | None]:
    start_text = raw_start.strip()
    end_text = raw_end.strip()

    start = None
    end = None
    if start_text:
        if not start_text.isdigit():
            return None, None, "Chapter start must be a positive integer"
        start = int(start_text)
        if start < 1:
            return None, None, "Chapter start must be a positive integer"
    if end_text:
        if not end_text.isdigit():
            return None, None, "Chapter end must be a positive integer"
        end = int(end_text)
        if end < 1:
            return None, None, "Chapter end must be a positive integer"
    if start is not None and end is not None and end < start:
        return None, None, "Chapter end must be greater than or equal to start"
    return start, end, None


class NewFileDialog(ModalScreen[NewFileResult | None]):
    BINDINGS = [
        Binding("escape", "close_dialog", "Close", priority=True),
    ]

    def __init__(
        self,
        *,
        chapter_start: int | None = None,
        chapter_end: int | None = None,
    ) -> None:
        super().__init__()
        self._chapter_start = chapter_start
        self._chapter_end = chapter_end

    def compose(self) -> ComposeResult:
        with Container(id="new-file-dialog"):
            yield Static("New File", id="new-file-title")
            yield Static("File path", classes="dialog-label")
            yield Input(placeholder="/path/to/book.epub", id="new-path-input")
            yield Static("Release ID", classes="dialog-label")
            yield Input(placeholder="e.g. v3.2", id="new-release-input")
            yield Static("Run ID", classes="dialog-label")
            yield Input(placeholder="e.g. run-1", id="new-run-input")
            yield Static("Chapter range (optional)", classes="dialog-label")
            with Horizontal(classes="chapter-bounds"):
                yield Input(
                    value="" if self._chapter_start is None else str(self._chapter_start),
                    placeholder="Start",
                    id="new-start-input",
                )
                yield Input(
                    value="" if self._chapter_end is None else str(self._chapter_end),
                    placeholder="End",
                    id="new-end-input",
                )
            with Horizontal(id="dialog-buttons"):
                yield Button("[[ SUBMIT ]]", id="new-submit", variant="primary")
                yield Button("[[ CANCEL ]]", id="new-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-cancel":
            self.dismiss(None)
            return
        if event.button.id != "new-submit":
            return

        raw_path = self.query_one("#new-path-input", Input).value.strip()
        release = self.query_one("#new-release-input", Input).value.strip()
        run_id = self.query_one("#new-run-input", Input).value.strip()
        chapter_start, chapter_end, bounds_error = parse_chapter_bounds(
            self.query_one("#new-start-input", Input).value,
            self.query_one("#new-end-input", Input).value,
        )

        if not raw_path:
            self.notify("File path is required", severity="error", timeout=3)
            return
        if not release:
            self.notify("Release ID is required", severity="error", timeout=3)
            return
        if not run_id:
            self.notify("Run ID is required", severity="error", timeout=3)
            return
        if bounds_error:
            self.notify(bounds_error, severity="error", timeout=4)
            return

        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            self.notify(f"Path does not exist: {path}", severity="error", timeout=4)
            return
        if not path.is_file():
            self.notify(f"Not a file: {path}", severity="error", timeout=4)
            return
        if path.suffix.lower() != ".epub":
            self.notify("Path must be an .epub file", severity="error", timeout=4)
            return
        try:
            with open(path, "rb"):
                pass
        except PermissionError:
            self.notify(f"File not readable: {path}", severity="error", timeout=4)
            return

        self.dismiss(
            NewFileResult(
                input_path=path,
                release_id=release,
                run_id=run_id,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
            )
        )

    def action_close_dialog(self) -> None:
        self.dismiss(None)


class ResumeRunDialog(ModalScreen[ResumeRunResult | None]):
    BINDINGS = [
        Binding("escape", "close_dialog", "Close", priority=True),
    ]

    def __init__(
        self,
        *,
        chapter_start: int | None = None,
        chapter_end: int | None = None,
    ) -> None:
        super().__init__()
        self._chapter_start = chapter_start
        self._chapter_end = chapter_end

    def compose(self) -> ComposeResult:
        with Container(id="resume-run-dialog"):
            yield Static("Resume Run", id="resume-run-title")
            yield Static("Release ID", classes="dialog-label")
            yield Input(placeholder="e.g. v3.2", id="resume-release-input")
            yield Static("Run ID", classes="dialog-label")
            yield Input(placeholder="e.g. run-1", id="resume-run-input")
            yield Static("Chapter range (optional)", classes="dialog-label")
            with Horizontal(classes="chapter-bounds"):
                yield Input(
                    value="" if self._chapter_start is None else str(self._chapter_start),
                    placeholder="Start",
                    id="resume-start-input",
                )
                yield Input(
                    value="" if self._chapter_end is None else str(self._chapter_end),
                    placeholder="End",
                    id="resume-end-input",
                )
            with Horizontal(id="dialog-buttons"):
                yield Button("[[ SUBMIT ]]", id="resume-submit", variant="primary")
                yield Button("[[ CANCEL ]]", id="resume-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "resume-cancel":
            self.dismiss(None)
            return
        if event.button.id != "resume-submit":
            return

        release = self.query_one("#resume-release-input", Input).value.strip()
        run_id = self.query_one("#resume-run-input", Input).value.strip()
        chapter_start, chapter_end, bounds_error = parse_chapter_bounds(
            self.query_one("#resume-start-input", Input).value,
            self.query_one("#resume-end-input", Input).value,
        )

        if not release:
            self.notify("Release ID is required", severity="error", timeout=3)
            return
        if not run_id:
            self.notify("Run ID is required", severity="error", timeout=3)
            return
        if bounds_error:
            self.notify(bounds_error, severity="error", timeout=4)
            return

        self.dismiss(
            ResumeRunResult(
                input_path=None,
                release_id=release,
                run_id=run_id,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
            )
        )

    def action_close_dialog(self) -> None:
        self.dismiss(None)
