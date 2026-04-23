# Resemantica Docs

This directory is the implementation-facing documentation suite for Resemantica.

Reading order:

1. `00-foundation/system-overview.md`
2. `00-foundation/glossary-of-terms.md`
3. `00-foundation/decision-rules.md`
4. `00-foundation/hashing-protocol.md`
5. `10-architecture/module-boundaries.md`
6. `10-architecture/runtime-lifecycle.md`
7. `10-architecture/storage-topology.md`
8. `20-lld/`
9. `30-operations/repo-map.md`
10. `30-operations/agent-workflow.md`
11. `40-tasks/`

Rules:

- `../DECISIONS.md` is the active source of truth when implementation docs conflict.
- Root docs define product intent and high-level contracts.
- `docs/20-lld/` defines implementation behavior for each subsystem slice.
- `docs/30-operations/repo-map.md` tracks the actual code layout as it evolves.
- `docs/40-tasks/` contains bounded execution briefs sized for one coder agent each.
- Any change to a public interface, artifact shape, or package boundary must update the relevant doc in this tree.
