# LLD 23: TUI Minimal Orientation

## Summary

Task 23 adds minimal orientation affordances to the existing Textual TUI. The current screens and keybindings work, but the shared shell does not consistently tell the operator where they are or how to discover the screen map. This slice adds persistent active-screen labeling and a small help overlay without changing workflows or redesigning screen content.

The design is intentionally conservative: one central metadata source drives screen bindings, header/footer labels, and help content so navigation copy cannot drift across the TUI.

## Public Interfaces

Navigation metadata:

- Screen number: `1` through `9`
- Screen id: Textual screen name such as `dashboard` or `warnings`
- Short label: compact footer/help label such as `Prep`
- Title: header/help title such as `Dashboard`
- Purpose: one-line help description

Shared shell:

- Header includes a location widget rendered as `Screen N/9 Title`.
- Footer includes active screen context and core keys: `Active: N Title | 1-9 Switch  ? Help  q Quit`.

Help overlay:

- Global `?` binding opens a modal help screen.
- Help lists all nine primary screens in numeric order.
- Help lists the core navigation keys.
- `escape` and `?` close the modal and return to the previously active primary screen.

## Implementation Details

Add `src/resemantica/tui/navigation.py`:

- Define a small immutable metadata type for primary screens.
- Export `SCREEN_INFOS` in navigation order.
- Export lookup helpers by screen id and screen class name.
- Keep class-name lookup in this module so `BaseScreen` can derive its location without each screen duplicating metadata.

Update `ResemanticaApp`:

- Build `SCREENS` from the existing screen classes plus the new help screen.
- Keep the nine current numeric bindings unchanged.
- Add `Binding("?", "show_help", "Help", priority=True)`.
- Add `action_show_help()` that determines the current primary screen and pushes `HelpScreen`.

Update `BaseScreen`:

- Add `#header-screen-location` to the header row.
- Populate it from navigation metadata during `_update_header()`.
- Update footer key copy during `_update_footer()`.
- Keep this logic in the shared shell so every primary screen gets identical orientation behavior.

Add `HelpScreen`:

- Implement as a `ModalScreen`.
- Render a compact panel containing current location, screen list, and key list.
- Bind `escape` and `?` to close the modal.
- Avoid workflow state access; help must be static except for current-screen metadata.

Update stylesheet:

- Give the location label a fixed compact width.
- Style the help modal panel, title, section labels, and dim text using the existing Palenight palette.
- Do not change the main TUI layout or palette.

## Tests

- Mounted app starts on dashboard and header renders `Screen 1/9 Dashboard`.
- Mounted app footer renders `Active: 1 Dashboard` and `? Help`.
- Pressing `4` updates the header to `Screen 4/9 Warnings`.
- Pressing `9` updates the header to `Screen 9/9 Settings`.
- Pressing `?` opens help and shows all nine primary screen labels.
- Pressing `escape` closes help and restores the previous primary screen.

Run:

- `uv run --with pytest pytest tests/tui -q`
- `uv run --with ruff ruff check src/resemantica/tui tests/tui`
- `uv run --with mypy mypy src/resemantica/tui --ignore-missing-imports`

## Assumptions

- Minimal orientation is the only goal for this slice.
- Help content is static navigation guidance, not screen-specific documentation.
- The chapter spine remains dedicated to chapter progress, not screen navigation.
- Textual modal behavior is sufficient; no custom overlay stack is needed.
