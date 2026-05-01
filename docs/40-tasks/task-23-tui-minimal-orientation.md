# Task 23: TUI Minimal Orientation

## Milestone And Depends On

Milestone: M23

Depends on: M22

## Goal

Make the existing TUI screens self-orienting so operators always know which screen they are viewing and can quickly discover the 1-9 navigation map without changing workflows or redesigning the interface.

## Scope

In:

- Add central metadata for the nine primary TUI screens: number, screen id, label, title, and one-line purpose.
- Show the active screen location in the shared header, e.g. `Screen 4/9 Warnings`.
- Keep footer navigation concise and discoverable, e.g. `Active: 4 Warnings | 1-9 Switch  ? Help  q Quit`.
- Add a `?` keybinding that opens a lightweight modal help overlay.
- Show all nine screen shortcuts and core keys in the help overlay.
- Close help with `escape` and `?`, returning to the prior screen.
- Add mounted Textual tests for screen location updates and help behavior.
- Update `lld-23-tui-minimal-orientation.md` to stay in sync.

Out:

- Adding or removing primary screens.
- Replacing the chapter spine with a navigation rail.
- Redesigning the TUI layout, color system, or screen content.
- Adding onboarding flows, tutorials, mouse navigation, or animations.
- Changing workflow actions inside individual screens.

## Owned Files Or Modules

- `src/resemantica/tui/app.py`
- `src/resemantica/tui/navigation.py`
- `src/resemantica/tui/screens/base.py`
- `src/resemantica/tui/screens/help.py`
- `src/resemantica/tui/screens/__init__.py`
- `src/resemantica/tui/palenight.tcss`
- `tests/tui/`

## Interfaces To Satisfy

- `ResemanticaApp` keeps the existing `1` through `9` screen bindings and adds `?` for help.
- Shared header includes a stable location label for the active primary screen.
- Shared footer includes the active screen label plus `1-9`, `?`, and `q` key hints.
- Help modal lists the nine primary screens and their one-line purposes.
- Help modal lists core navigation keys: `1-9`, `?`, `escape`, and `q`.
- Help modal closes without changing the underlying active primary screen.

## Tests Or Smoke Checks

- Mounted app test starts on dashboard and renders `Screen 1/9 Dashboard`.
- Mounted app test switches to screen `4` and renders `Screen 4/9 Warnings`.
- Mounted app test switches to screen `9` and renders `Screen 9/9 Settings`.
- Mounted app test opens help with `?` and verifies all nine screen labels are present.
- Mounted app test closes help with `escape` and returns to the previous primary screen.
- Run `uv run --with pytest pytest tests/tui -q`.
- Run `uv run --with ruff ruff check src/resemantica/tui tests/tui`.
- Run `uv run --with mypy mypy src/resemantica/tui --ignore-missing-imports`.

## Done Criteria

- Operators can identify the active screen from the shared header on every primary screen.
- Operators can discover navigation from the shared footer without opening documentation.
- Pressing `?` opens a help overlay that explains where each primary screen lives.
- Pressing `escape` or `?` closes help and preserves the prior screen.
- Tests cover the orientation header, footer, and help modal behavior.
- `docs/20-lld/lld-23-tui-minimal-orientation.md` is implemented and kept in sync.
