# Handover Next Session

## M11 Status: COMPLETE

### Implemented

- **Scoped cleanup** in `src/resemantica/orchestration/cleanup.py`:
  - `_collect_scope_artifacts()`: scope-aware artifact collection for `run`, `translation`, `preprocess`, `cache`, `all`
  - `plan_cleanup()`: creates cleanup plan with deletable/preserved artifacts and estimated space
  - `apply_cleanup()`: executes cleanup based on plan, generates cleanup report, deletes SQLite rows
  - Protection of `tracking.db`, `cleanup_plan.json`, `cleanup_report.json` in `all` scope

- **CLI improvements**:
  - `cleanup-plan`: shows formatted preview with deletable/preserved artifacts and estimated space
  - `cleanup-apply`: shows detailed report with deleted files/dirs and SQLite rows deleted

- **Tests**: 7 new M11 tests in `tests/orchestration/` (22 total)
  - `test_scope_run_deletes_only_run_dir`
  - `test_scope_translation_deletes_only_translation`
  - `test_scope_preprocess_deletes_preprocess_artifacts`
  - `test_scope_all_preserves_tracking_db`
  - `test_cleanup_apply_refuses_without_plan`
  - `test_cleanup_apply_refuses_scope_mismatch`
  - `test_cleanup_report_generated`

### Verified Commands

```bash
uv run --extra dev ruff check src/resemantica tests/orchestration
uv run --extra dev mypy src/resemantica
uv run --extra dev pytest tests/epub tests/translation tests/glossary tests/summaries tests/idioms tests/graph tests/packets tests/orchestration
```

### Next Objective

Start **M12** (Unified Textual TUI):

- Task brief: `docs/40-tasks/task-12-tui-core.md`
- LLD: `docs/20-lld/lld-12-tui-core.md`

### Working Tree State

New files:
- None

Modified files:
- `src/resemantica/orchestration/cleanup.py` (M11: scoped cleanup implemented)
- `src/resemantica/cli.py` (M11: improved cleanup-plan and cleanup-apply output)
- `tests/orchestration/test_orchestration.py` (M11: 7 new tests added)
- `IMPLEMENTATION_PLAN.md` (M11 checklist: complete)
- `docs/30-operations/handover-next-session.md` (updated for M11)

No push performed.
