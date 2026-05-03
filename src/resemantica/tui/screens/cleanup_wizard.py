from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static

from resemantica.tui.screens.base import BaseScreen

SCOPES: list[str] = ["run", "translation", "preprocess", "cache", "all", "factory"]


def _categorize(path_str: str) -> str:
    lower = path_str.lower()
    if "/runs/" in lower:
        if "translation" in lower:
            return "Translation output"
        return "Run directory"
    if "resemantica.db" in lower:
        return "Global database"
    if lower.endswith("/releases") or lower.rstrip("/").endswith("/releases"):
        return "All releases"
    for keyword, category in [
        ("extracted", "Extracted text"),
        ("glossary", "Glossary candidates"),
        ("summaries", "Draft summaries"),
        ("idioms", "Idiom policies"),
        ("graph", "Knowledge graph"),
        ("packets", "Chapter packets"),
        (".cache", "LLM cache"),
    ]:
        if keyword in lower:
            return category
    return "Other"


def _format_size(bytes_val: int) -> str:
    if bytes_val < 0:
        return "unknown"
    if bytes_val < 1024:
        return f"{bytes_val} B"
    if bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    return f"{bytes_val / (1024 * 1024):.1f} MB"


class CleanupWizardScreen(BaseScreen):
    BINDINGS = [
        Binding("s", "cycle_scope", "Scope"),
        Binding("p", "preview_or_advance", "Preview"),
        Binding("b", "back", "Back"),
        Binding("a", "confirm_and_apply", "Apply"),
        Binding("escape", "return_to_artifact", "Cancel", priority=True),
    ]

    def on_mount(self) -> None:
        self._step: int = 1
        self._scope_index: int = 0
        self._scope: str = "run"
        self._plan_result: dict | None = None
        self._apply_result: dict | None = None
        self._error: str | None = None
        super().on_mount()
        self._refresh_plan()
        self._render_step()

    def _content_widgets(self) -> ComposeResult:
        with Container(id="cleanup-wizard-content"):
            yield Static("", id="wizard-step-indicator", classes="section-title")
            yield Static("", id="wizard-scope-info")
            yield Static("", id="wizard-main-content")
            yield Static("", id="wizard-key-hints")

    def _refresh_all(self) -> None:
        super()._refresh_all()
        self._render_step()

    def action_cycle_scope(self) -> None:
        if self._step not in (1, 2):
            return
        self._scope_index = (self._scope_index + 1) % len(SCOPES)
        self._scope = SCOPES[self._scope_index]
        if self._step == 2:
            self._step = 1
        self._refresh_plan()
        self._render_step()

    def action_preview_or_advance(self) -> None:
        if self._step == 1:
            self._step = 2
        elif self._step == 2:
            self._step = 3
        else:
            return
        self._render_step()

    def action_back(self) -> None:
        if self._step > 1:
            self._step -= 1
            self._render_step()

    def action_confirm_and_apply(self) -> None:
        if self._step != 3:
            return
        if self._scope == "factory":
            try:
                from resemantica.orchestration.cleanup import apply_cleanup
                result = apply_cleanup("", "", scope=self._scope)
                self._apply_result = result
                self._error = None
                self._step = 4
            except Exception as exc:
                self._error = str(exc)
                self._apply_result = None
                self._step = 4
            self._render_step()
            return
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if not release_id or not run_id:
            self._error = "Need release_id and run_id to apply cleanup."
            self._render_step()
            return

        try:
            from resemantica.orchestration.cleanup import apply_cleanup
            result = apply_cleanup(release_id, run_id, scope=self._scope)
            self._apply_result = result
            self._error = None
            self._step = 4
        except Exception as exc:
            self._error = str(exc)
            self._apply_result = None
            self._step = 4
        self._render_step()

    async def action_return_to_artifact(self) -> None:
        await self.app.action_switch_screen("artifact")

    def _refresh_plan(self) -> None:
        if self._scope == "factory":
            try:
                from resemantica.orchestration.cleanup import plan_cleanup
                self._plan_result = plan_cleanup(
                    "", "", scope=self._scope, dry_run=True
                )
                self._error = None
            except Exception as exc:
                self._plan_result = None
                self._error = str(exc)
            return
        release_id = self._get_release_id()
        run_id = self._get_run_id()
        if not release_id or not run_id:
            self._plan_result = None
            return
        try:
            from resemantica.orchestration.cleanup import plan_cleanup
            self._plan_result = plan_cleanup(
                release_id, run_id, scope=self._scope, dry_run=True
            )
            self._error = None
        except Exception as exc:
            self._plan_result = None
            self._error = str(exc)

    def _render_step(self) -> None:
        indicator = self.query_one("#wizard-step-indicator", Static)
        indicator.update(f"Cleanup Wizard{' ' * 24}Step {self._step}/4")

        scope_info = self.query_one("#wizard-scope-info", Static)
        deletable = []
        preserved = []
        estimated = -1
        sqlite_count = 0
        if self._plan_result:
            deletable = self._plan_result.get("deletable_artifacts", [])
            preserved = self._plan_result.get("preserved_artifacts", [])
            estimated = self._plan_result.get("estimated_space_bytes", -1)
            sqlite_count = len(self._plan_result.get("sqlite_rows", []))

        scope_info.update(
            f"Scope: [bold cyan]{self._scope}[/]"
            f"  |  {len(deletable)} item(s)  ~{_format_size(estimated)}"
        )

        main = self.query_one("#wizard-main-content", Static)
        hints = self.query_one("#wizard-key-hints", Static)

        if self._error and self._step != 3:
            main.update(f"[red]Error: {self._error}[/]")
            hints.update("[dim]s[/]=Scope  [dim]p[/]=Preview  [dim]Esc[/]=Cancel")
            return

        if self._step == 1:
            self._render_step_1(main, hints, deletable, preserved, estimated, sqlite_count)
        elif self._step == 2:
            self._render_step_2(main, hints, deletable, preserved, estimated, sqlite_count)
        elif self._step == 3:
            self._render_step_3(main, hints, deletable, preserved, estimated, sqlite_count)
        elif self._step == 4:
            self._render_step_4(main, hints)

    def _render_step_1(
        self,
        main: Static,
        hints: Static,
        deletable: list[str],
        preserved: list[str],
        estimated: int,
        sqlite_count: int,
    ) -> None:
        lines: list[str] = []
        if self._plan_result is None and self._scope != "factory":
            lines.append("[dim]No release or run context. Set release/run via Dashboard or New File dialog.[/]")
        elif self._scope == "factory":
            lines.append("[bold red]FACTORY RESET[/]")
            lines.append("This will delete [bold]ALL releases[/] and the [bold]global database[/].")
            lines.append("")
            lines.append("[dim]Press [bold]p[/] to preview what will be deleted.[/]")
        else:
            lines.append(f"[bold]Scope:[/] [cyan]{self._scope}[/]")
            lines.append(f"[bold]Items to delete:[/] {len(deletable)}")
            lines.append(f"[bold]Estimated space:[/] {_format_size(estimated)}")
            if sqlite_count:
                lines.append(f"[bold]SQLite tables affected:[/] {sqlite_count}")
            lines.append("")
            lines.append("[dim]Press [bold]p[/] to preview what will be deleted.[/]")
        main.update("\n".join(lines))
        hints.update("[dim]s[/]=Cycle scope  [dim]p[/]=Preview  [dim]Esc[/]=Cancel")

    def _render_step_2(
        self,
        main: Static,
        hints: Static,
        deletable: list[str],
        preserved: list[str],
        estimated: int,
        sqlite_count: int,
    ) -> None:
        lines: list[str] = []
        if self._plan_result is None:
            lines.append("[red]No cleanup plan available. Go back and select a scope.[/]")
            main.update("\n".join(lines))
            hints.update("[dim]b[/]=Back  [dim]Esc[/]=Cancel")
            return

        if self._scope == "factory":
            lines.append("[bold red]FACTORY RESET — EVERYTHING WILL BE DELETED[/]")
            lines.append("")

        lines.append(f"[bold orange]WILL DELETE[/bold orange] ({len(deletable)} items, ~{_format_size(estimated)})")
        grouped: dict[str, list[str]] = {}
        for a in deletable:
            cat = _categorize(a)
            grouped.setdefault(cat, []).append(a)
        for cat, items in grouped.items():
            lines.append(f"  [bold]{cat}[/] ({len(items)})")
            for p in items[:4]:
                lines.append(f"    [orange]{p}[/]")
            if len(items) > 4:
                lines.append(f"    [dim]... and {len(items) - 4} more[/]")

        lines.append("")
        lines.append(f"[bold green]WILL PRESERVE[/bold green] ({len(preserved)} items)")
        for p in preserved[:6]:
            lines.append(f"  [green]{p}[/]")
        if len(preserved) > 6:
            lines.append(f"  [dim]... and {len(preserved) - 6} more[/]")

        lines.append("")
        lines.append(f"[bold]SQLite rows to delete:[/] {sqlite_count}")

        main.update("\n".join(lines))
        hints.update("[dim]b[/]=Back  [dim]p[/]=Confirm  [dim]Esc[/]=Cancel")

    def _render_step_3(
        self,
        main: Static,
        hints: Static,
        deletable: list[str],
        preserved: list[str],
        estimated: int,
        sqlite_count: int,
    ) -> None:
        lines: list[str] = []
        if self._plan_result is None:
            lines.append("[red]No cleanup plan available. Press [bold]b[/] to go back.[/]")
            main.update("\n".join(lines))
            hints.update("[dim]b[/]=Back  [dim]Esc[/]=Cancel")
            return

        if self._error:
            lines.append(f"[red]Error: {self._error}[/]")
            main.update("\n".join(lines))
            hints.update("[dim]b[/]=Back  [dim]Esc[/]=Cancel")
            return

        if self._scope == "factory":
            lines.append("[bold red]╔══════════════════════════════════════╗[/]")
            lines.append("[bold red]║        ⚠ FACTORY RESET ⚠           ║[/]")
            lines.append("[bold red]║  This will delete ALL releases,    ║[/]")
            lines.append("[bold red]║  ALL runs, and the global database. ║[/]")
            lines.append("[bold red]║  The entire artifact directory      ║[/]")
            lines.append("[bold red]║  will be wiped clean.               ║[/]")
            lines.append("[bold red]╚══════════════════════════════════════╝[/]")
            lines.append("")

        lines.append("[bold red]This will permanently delete:[/]")
        lines.append("")
        lines.append(f"  [bold]{len(deletable)} files/directories[/] (~{_format_size(estimated)})")
        lines.append(f"  [bold]{sqlite_count} SQLite row deletions[/]")
        lines.append("")
        lines.append("[red bold]This cannot be undone.[/]")
        lines.append("")
        lines.append("[bold]Press [cyan]a[/] to confirm and apply.[/]")

        main.update("\n".join(lines))
        hints.update("[dim]b[/]=Back  [bold][red]a[/]=Apply[/]  [dim]Esc[/]=Cancel")

    def _render_step_4(self, main: Static, hints: Static) -> None:
        lines: list[str] = []
        if self._error:
            lines.append(f"[red]Cleanup failed: {self._error}[/]")
        elif self._apply_result:
            success = self._apply_result.get("success", True)
            if success or success is True:
                lines.append("[bold green]Cleanup completed successfully[/]")
            else:
                lines.append(f"[red]Cleanup reported issues: {self._apply_result.get('message', '')}[/]")
            lines.append("")
            lines.append(f"  Files deleted:       {len(self._apply_result.get('deleted_files', []))}")
            lines.append(f"  Directories deleted: {len(self._apply_result.get('deleted_dirs', []))}")
            lines.append(f"  SQLite rows deleted: {self._apply_result.get('sqlite_rows_deleted', 0)}")
            errors = self._apply_result.get("errors", [])
            if errors:
                lines.append(f"  Errors:              [red]{len(errors)}[/]")
                for e in errors[:3]:
                    lines.append(f"    [red]{e}[/]")
            else:
                lines.append("  Errors:              none")
        else:
            lines.append("[yellow]No result available.[/]")

        main.update("\n".join(lines))
        hints.update("[dim]Press [bold]Esc[/] to return to Artifact screen[/]")
