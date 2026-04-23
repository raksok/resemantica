# Task 12: CLI And TUI

- **Milestone:** M12
- **Depends on:** M10, M11

## Goal

Implement operator-facing CLI and TUI surfaces on top of orchestration without duplicating workflow logic.

## Scope

In:

- command parsing and dispatch
- event-driven TUI presenters and screens
- artifact inspection shortcuts

Out:

- alternate execution paths inside the UI

## Owned Files Or Modules

- `src/resemantica/cli.py`
- `src/resemantica/tui/`
- `tests/cli/`
- `tests/tui/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-12-cli-and-tui.md`
- TUI layout: `../20-lld/lld-12-tui-layout.md`
- repo rules: `../30-operations/repo-map.md`

## Tests Or Smoke Checks

- CLI command dispatch tests
- presenter tests driven by event fixtures
- warning/error state propagation

## Done Criteria

- operator can drive supported workflows from CLI or TUI
- surfaces show orchestration truth without hidden duplicate logic
