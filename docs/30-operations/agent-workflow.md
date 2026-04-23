# Agent Workflow

## Purpose

This file describes how coder agents should pick work, avoid overlap, validate changes, and keep the documentation suite useful.

## Work Selection

- start from a task brief in `docs/40-tasks/`
- read the referenced LLD before editing code
- claim one bounded slice at a time
- do not expand scope because a neighboring subsystem looks unfinished

## Ownership Rules

- own the files and modules named in the task brief
- avoid editing other subsystems unless the task explicitly requires an interface touchpoint
- if another task has already claimed a boundary, adapt to it instead of rewriting it

## Change Rules

- make surgical changes only
- match the documented package layout and boundary rules
- do not invent new stores, artifact shapes, or commands when a doc already defines them
- if a required decision is missing, add it to the relevant doc before or with the code change

## Validation Rules

- run the smallest validation that proves the slice works
- do not mark work complete without tests or smoke checks named in the task brief
- report residual gaps explicitly if a tool is unavailable

## Documentation Update Rules

- update the relevant LLD when public behavior changes
- update `repo-map.md` when the real layout changes
- update the task brief status or replace it with a follow-up brief when new work is created

## Escalation Rules

- if code and doc disagree, stop and resolve the discrepancy explicitly
- if a task would force cross-cutting refactors, split it into new task briefs instead of freelancing
