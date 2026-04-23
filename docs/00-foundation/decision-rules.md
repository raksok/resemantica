# Decision Rules

## Non-Negotiable Invariants

- Source Chinese text is the ultimate truth.
- Locked glossary is naming truth.
- Validated Chinese summaries are continuity truth.
- English summaries are derived artifacts only.
- Working state never silently becomes authority state.
- Runtime translation reads chapter packets and paragraph bundles instead of broad live retrieval.
- Deterministic rules outrank fuzzy matching and model guesses.
- Model output never writes directly into authority state without validation.
- Placeholder preservation and XHTML restoration are deterministic code responsibilities.
- The graph database is LadybugDB (`import ladybug as lb`). Using `import kuzu` is a hard error.
- Milestone order (M1→M14) governs execution. Task brief IDs match milestone order: `task-01` maps to M1 through `task-14` maps to M14.

## Dependency Direction

Allowed high-level dependency flow:

```text
epub -> db/contracts -> preprocessing subsystems -> packets -> translation -> reconstruction
                                      \-> orchestration/tracking -> cli/tui
```

Rules:

- `epub/` must not depend on `translation/`, `packets/`, or `tui/`.
- `translation/` may consume packet outputs and locked glossary lookups, but must not own glossary promotion or summary validation.
- `tui/` must observe orchestration events, not implement workflow rules itself.
- `cli.py` is a thin entrypoint over orchestration and subsystem services.
- Repositories own storage access; business rules belong in services/workflows.

## Documentation Sync Rules

- `DECISIONS.md` resolves conflicts between root specs, LLDs, operations docs, and task briefs.
- Update the relevant LLD when a public module API, command, schema, artifact path, or stage behavior changes.
- Update `repo-map.md` when directories, entrypoints, or ownership boundaries change materially.
- Record conflicts between code and doc as an explicit decision note or follow-up task. Do not silently diverge.
- If code and LLD disagree during early implementation, treat the LLD as intended behavior unless a newer decision note says otherwise.

## Change Discipline

- Prefer the smallest slice that leaves behind runnable validation.
- Do not create abstractions for speculative future modes.
- Preserve separation between authority state, working state, and operational state from the first schema draft.
- Keep milestone work vertically sliceable so one agent can own it end to end.
