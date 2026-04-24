# Task Briefs

Each active `task-*.md` file in this directory is a bounded execution brief for one coder agent.

Required sections:

- Milestone and Depends On (execution order fields)
- Goal
- Scope
- Owned files or modules
- Interfaces to satisfy
- Tests or smoke checks
- Done criteria

Start with the task matching the next implementation milestone. Task numbers now match milestone numbers: `task-05-*` is M5, `task-14-*` is M14. If a task grows beyond one bounded slice, split it into a new brief rather than stretching the original.

Packet integration is not a standalone task. The retired redirect is kept only as `retired-packet-integration.md`; active packet work belongs to Task 08.

## Canonical Milestone Order

Always follow the milestone sequence below.

| Milestone | Task Brief | Depends On | Description |
|-----------|------------|------------|-------------|
| M1 | task-01 | — | EPUB Round-Trip |
| M2 | task-02 | M1 | Single-Chapter Translation |
| M3 | task-03 | M1 | Canonical Glossary |
| M4 | task-04 | M1 | Summary Memory |
| M5 | task-05 | M1, M3 | Idiom Workflow |
| M6 | task-06 | M1, M3, M4 | Graph MVP |
| M7 | task-07 | M6 | Lightweight World Model |
| M8 | task-08 | M3, M4, M5, M7 | Chapter Packets (with graph) |
| M9 | task-09 | M2, M8 | Pass 3 + Risk Handling |
| M10 | task-10 | M1–M9 | Orchestration + Production |
| M11 | task-11 | M10 | Cleanup Workflow |
| M12 | task-12 | M10, M11 | CLI + TUI |
| M13 | task-13 | M10 | Observability + Evaluation |
| M14A | task-14a | M13 | Graph Pipeline Drift Fix — LLM Extraction |
| M14B | task-14b | M14A, M10–M13 | Batch Pilot |
