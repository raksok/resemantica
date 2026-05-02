# Kaizen Analysis — Consolidated

Date: 2026-05-01
Status: Pending implementation
Sources: `kaizen` sweep + lint/typecheck/grep dups/dead-code scan
Supersedes: previous `kaizen-decisions.md` + `kaizen-supplement.md` (both merged here)

All 269 tests pass. No breaking changes. Work is grouped into a single smooth execution pass: edit each file once, verify at checkpoints, finish clean.

---

## Item Catalog

| # | Type | File(s) | What |
|---|------|---------|------|
| B1 | Bug | `tui/screens/base.py:742` | `{error}` undefined — replace with `{exc}` |
| B2 | Bug | `tui/screens/base.py:9` | Unused `App` import (F401) — remove |
| B3 | Bug | `summaries/validators.py:237` | JSON parse failure returns `[]` indistinguishable from clean — return `["<parse_error>"]` + log warning |
| B4 | Bug | `orchestration/events.py:63` | Subscriber exceptions swallowed at `warning` — escalate to `logger.error` |
| B5 | Bug | `orchestration/cleanup.py:72-80` | `_estimate_size` silently swallows OSError — return `-1` for unmeasurable paths |
| B6 | Bug | `settings.py:129-140` | `_as_int`/`_as_float` lose field-name context on ValueError — wrap in try/except with field name |
| H1 | Hygiene | `db/sqlite.py:44-67` | 9 bare `print("DEBUG: ...")` — convert to `logger.debug()` |
| H2 | Hygiene | `glossary/pipeline.py:94` | `logging.getLogger` instead of project-standard `loguru` — replace with `logger` |
| H3 | Hygiene | `.gitignore` | `.codex/` tool artifact not ignored — add entry |
| H4 | Hygiene | `orchestration/models.py:21`, `orchestration/cleanup.py:90` | Naked `dict` / `dict[str, Any]` — use `dict[str, object]` |
| H5 | Hygiene | `settings.py:47` | `pass3_default = True` contradicts TOML defaults — change to `False` |
| RF1 | Refactor | `packets/builder.py` + 36 other locations | 37 duplicate utility function defs — create `src/resemantica/utils.py`, import everywhere |
| RF2 | Refactor | `translation/validators.py`, `summaries/validators.py`, `graph/validators.py` | Three identical `ValidationResult` dataclass clones — create shared `src/resemantica/validators.py`, re-export |
| RF3 | Refactor | `db/extraction_repo.py` | Class pattern vs function pattern (all other repos use functions) — convert to module-level functions |
| RF4 | Refactor | `db/sqlite.py` + 5 repos | `ensure_*_schema` duplicated 5x — add single `ensure_schema(conn, name)` helper |
| RF5 | Refactor | `summaries/generator.py`, `summaries/derivation.py` | Identical 5-line `_glossary_context` formatter — extract to `summaries/__init__.py` |
| RF6 | Refactor | `db/idiom_repo.py`, `idioms/models.py`, callers | Idiom repo naming diverges from glossary — conform to `discovered → translate → promoted` vocabulary |
| RF7 | Refactor | `graph/models.py`, callers | `WorldModelEdge` + `GraphRelationship` dual dataclasses — merge into one + validation function |
| RF8 | Refactor | `tests/` (6+ files) | Duplicate test fixtures — create `tests/conftest.py` |
| J1 | JIT | `/main.py` | Dead — delete |
| J2 | JIT | `idioms/repo.py` | Stale wrapper class, zero callers — delete |
| J3 | JIT | `glossary/models.py:26` | Unused `CATEGORY_VALUES` — remove |
| J4 | JIT | `graph/models.py:40` | Unused `SUPPORTED_RELATIONSHIP_TYPES` — remove (also update import in `graph/validators.py`) |
| J5 | JIT | `db/sqlite.py:70` | Unused `get_schema_version()` — remove |
| CFG1 | Config | `pyproject.toml` | Missing runtime deps `rich`, `ebooklib`, `lxml` — add to `[project].dependencies` |
| CFG2 | Config | `pyproject.toml` | No `[tool.ruff]` / `[tool.mypy]` sections — add config |
| DEF1 | Defer | `cli.py`, `orchestration/runner.py`, `translation/pipeline.py`, `packets/builder.py` | Monolithic files >700 lines — split opportunistically |
| DEF2 | Defer | `orchestration/events.py` | Mixed event namespace delimiters — standardize on dots |
| DEF3 | Defer | `cli.py` | Duplicate CLI subcommands `run-production` / `run production` — deprecate one |
| DEF4 | Defer | Pipeline modules | Inconsistent status output (print vs loguru vs TUI) — standardize on logger |
| DEF5 | Defer | DB repos, `llm/cache.py`, `llm/tokens.py`, `epub/parser.py` | Untested layers — add tests opportunistically |
| UX1 | UI | `tui/screens/base.py:490-501` | Event tail: drop stage=name field, change severity padding to `SEVERITY:` colon format (requested during preprocessing screen work) |

---

## Single-Pass Execution Plan

Grouped by file touch. Each phase touches each file once. Run `pytest tests/ -q` after each phase to verify.

### Phase 1 — Deletions (3 min, no test impact)

| Step | File | Action |
|------|------|--------|
| 1.1 | `/main.py` | Delete file (J1) |
| 1.2 | `src/resemantica/idioms/repo.py` | Delete file (J2) |
| 1.3 | `.gitignore` | Add `.codex/` (H3) |

**Verify:** `ls main.py` confirms gone. `git status` shows deletions.

---

### Phase 2 — Single-file bug fixes & hygiene (15 min)

| Step | File | Action | Items |
|------|------|--------|-------|
| 2.1 | `src/resemantica/tui/screens/base.py` | Line 9: remove `App` from `from textual.app import App, ComposeResult`. Line 742: `{error}` → `{exc}` | B1, B2 |
| 2.2 | `src/resemantica/settings.py` | Line 47: `pass3_default: bool = True` → `False`. Lines ~129-140: wrap `_as_int`/`_as_float` in try/except with field-name `ValueError` | H5, B6 |
| 2.3 | `src/resemantica/glossary/pipeline.py` | Replace `logging.getLogger` usage with `from loguru import logger` (add import if missing) | H2 |
| 2.4 | `src/resemantica/glossary/models.py` | Remove `CATEGORY_VALUES: set[str]` | J3 |
| 2.5 | `src/resemantica/graph/models.py` | Remove `SUPPORTED_RELATIONSHIP_TYPES`. Remove `WorldModelEdge` dataclass + `to_graph_relationship`/`from_graph_relationship` methods. Add `validate_world_model_edge(rel: GraphRelationship) -> None`. Update any `WorldModelEdge` type refs to `GraphRelationship` | J4, RF7 |
| 2.6 | `src/resemantica/graph/validators.py` | Remove `SUPPORTED_RELATIONSHIP_TYPES` import. Replace any `WorldModelEdge` usage with `GraphRelationship` + call to `validate_world_model_edge` | J4, RF7 |
| 2.7 | `src/resemantica/summaries/validators.py` | In `validate_chinese_summary_content`: catch `json.JSONDecodeError`, log warning with raw text, return `["<parse_error>"]` instead of `[]` | B3 |
| 2.8 | `src/resemantica/orchestration/events.py` | In `EventBus.publish()`: change `logger.warning` to `logger.error` with subscriber name and `exception=True` | B4 |
| 2.9 | `src/resemantica/orchestration/cleanup.py` | In `_estimate_size`: if OSError, set `total = -1`. In return type annotations: `dict[str, Any]` → `dict[str, object]` | B5, H4 |
| 2.10 | `src/resemantica/orchestration/models.py` | `checkpoint: dict` → `checkpoint: dict[str, object]`. `metadata: dict` → `metadata: dict[str, object]` | H4 |
| 2.11 | `src/resemantica/db/sqlite.py` | Lines 44-67: replace all `print("DEBUG: ...")` with `logger.debug(...)`. Line 70: remove `get_schema_version()` function. Add `ensure_schema(conn: sqlite3.Connection, name: str) -> None` helper. Add `from loguru import logger` import | H1, J5, RF4 |

**Verify:** `uv run ruff check src/ && uv run pytest tests/ -q`

---

### Phase 3 — Configuration (5 min, no test impact)

| Step | File | Action | Items |
|------|------|--------|-------|
| 3.1 | `pyproject.toml` | Add `rich`, `ebooklib`, `lxml` to `[project].dependencies`. Add `[tool.ruff]` section. Add `[tool.mypy]` section | CFG1, CFG2 |

Suggested config:

```toml
[tool.ruff]
target-version = "py313"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "I", "W"]

[tool.mypy]
python_version = "3.13"
strict = false
warn_return_any = true
warn_unused_ignores = true
check_untyped_defs = true
```

**Verify:** `uv run ruff check src/ tests/ && uv run mypy src/`

---

### Phase 4 — Create shared utilities + dedup (30 min, shared module)

#### 4.1 Create `src/resemantica/utils.py`

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from resemantica.settings import AppConfig
from resemantica.llm.client import LLMClient
from resemantica.orchestration.events import emit_event


def _chapter_number_from_path(path: Path) -> int:
    stem = path.stem
    digits = "".join(c for c in stem if c.isdigit())
    return int(digits)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _build_llm_client(config: AppConfig, llm_client: LLMClient | None) -> LLMClient:
    if llm_client is not None:
        return llm_client
    return LLMClient(config)


def _emit(run_id: str, release_id: str, event_type: str, **kwargs: object) -> None:
    emit_event(run_id=run_id, release_id=release_id, event_type=event_type, **kwargs)
```

#### 4.2 Replace all local definitions with imports (RF1)

For each file below: remove the local function definition(s), add `from resemantica.utils import ...`. Keep only the functions that file actually uses.

| File | Remove | Import |
|------|--------|--------|
| `chapters/manifest.py:23` | `_chapter_number_from_path` | `_chapter_number_from_path` |
| `glossary/pipeline.py:36,40,48,78` | all 4 | `_chapter_number_from_path, _write_json, _build_llm_client, _emit` |
| `glossary/discovery.py:36` | `_chapter_number_from_path` | `_chapter_number_from_path` |
| `idioms/pipeline.py:38,42,50,80` | all 4 | `_chapter_number_from_path, _write_json, _build_llm_client, _emit` |
| `idioms/extractor.py:36` | `_chapter_number_from_path` | `_chapter_number_from_path` |
| `summaries/pipeline.py:40,47,55,62,96` | all 5 | `_read_json, _write_json, _chapter_number_from_path, _emit, _build_llm_client` |
| `summaries/derivation.py:12` | `_canonical_json` | `_canonical_json` |
| `graph/pipeline.py:35,39,86,116` | all 4 | `_chapter_number_from_path, _write_json, _build_llm_client, _emit` |
| `graph/extractor.py:96` | `_chapter_number_from_path` | `_chapter_number_from_path` |
| `graph/client.py:19` | `_canonical_json` | `_canonical_json` |
| `packets/builder.py:51,55,62,70,89` | all 5 | `_canonical_json, _read_json, _write_json, _emit, _chapter_number_from_path` |
| `packets/bundler.py:11` | `_canonical_json` | `_canonical_json` |
| `translation/pipeline.py:64,68,76,115` | `_read_json, _write_json, _build_llm_client` (keep `_emit_translation_event` — different signature) | `_read_json, _write_json, _build_llm_client` |
| `epub/extractor.py:103` | `_write_json` | `_write_json` |
| `epub/rebuild.py:105,109` | `_read_json, _write_json` | `_read_json, _write_json` |
| `db/summary_repo.py:13` | `_canonical_json` | `_canonical_json` |

**Verify:** `uv run ruff check src/ && uv run pytest tests/ -q`

---

### Phase 5 — Shared validation result protocol (10 min)

#### 5.1 Create `src/resemantica/validators.py` (RF2)

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ValidationResult:
    status: str = "pass"
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def combined_errors(self) -> list[str]:
        return self.errors + self.warnings
```

#### 5.2 Re-export in existing validators modules

| File | Action |
|------|--------|
| `translation/validators.py` | Replace local `ValidationResult` with `from resemantica.validators import ValidationResult` |
| `summaries/validators.py` | Replace local `SummaryValidationResult` with `from resemantica.validators import ValidationResult` (update all callers using `SummaryValidationResult` → `ValidationResult`) |
| `graph/validators.py` | Replace local `GraphValidationResult` with `from resemantica.validators import ValidationResult` (update all callers using `GraphValidationResult` → `ValidationResult`) |

**Verify:** `uv run ruff check src/ && uv run pytest tests/ -q`

---

### Phase 6 — Repo layer standardization (15 min)

#### 6.1 Dedup `ensure_*_schema` (RF4)

Replace each local `ensure_*_schema` with `ensure_schema(conn, "name")` from `db.sqlite`:

| File | Remove | Replace with |
|------|--------|-------------|
| `db/glossary_repo.py:11-13` | `ensure_glossary_schema()` + `apply_migrations` call | `ensure_schema(conn, "glossary")` |
| `db/graph_repo.py:11-13` | `ensure_graph_schema()` + `apply_migrations` call | `ensure_schema(conn, "graph")` |
| `db/idiom_repo.py:11-13` | `ensure_idiom_schema()` + `apply_migrations` call | `ensure_schema(conn, "idioms")` |
| `db/packet_repo.py:10-12` | `ensure_packet_schema()` + `apply_migrations` call | `ensure_schema(conn, "packets")` |
| `db/summary_repo.py:81-84` | `ensure_summary_schema()` + `apply_migrations` call | `ensure_schema(conn, "summaries")` |

#### 6.2 Convert `ExtractionRepo` class to functions (RF3)

| File | Action |
|------|--------|
| `db/extraction_repo.py` | Remove `class ExtractionRepo`. Convert `record_extraction_metadata` and `list_chapter_blocks` to module-level functions with `conn` as first param |
| `epub/extractor.py` | Update callers from `repo.method()` to `function(conn, ...)` |

#### 6.3 Conform idiom naming to glossary (RF6)

| File | Old | New |
|------|-----|-----|
| `db/idiom_repo.py` | `insert_detected_candidates` | `upsert_discovered_candidates` |
| `db/idiom_repo.py` | `mark_candidate_approved` | `mark_candidate_promoted` |
| `db/idiom_repo.py` | `prompt_version` (SQL column) | `analyst_prompt_version` |
| `idioms/models.py` | `prompt_version: str` field | `analyst_prompt_version: str` |
| `idioms/pipeline.py` | calls to `insert_detected_candidates` | `upsert_discovered_candidates` |
| `idioms/pipeline.py` | calls to `mark_candidate_approved` | `mark_candidate_promoted` |

**Verify:** `uv run ruff check src/ && uv run pytest tests/ -q`

---

### Phase 7 — Summaries dedup + test conftest (15 min)

#### 7.1 Extract shared glossary context formatter (RF5)

| File | Action |
|------|--------|
| `summaries/__init__.py` | Add `_format_glossary_context(entries)` function |
| `summaries/generator.py` | Remove local `_format_glossary_context`, import from `summaries.__init__` |
| `summaries/derivation.py` | Remove local copy, import from `summaries.__init__` |

#### 7.2 Create test conftest (RF8)

Create `tests/conftest.py` with shared fixtures (`_write_extracted_chapter`, `_make_config`, `_write_fixture_epub`, `_make_event`). Remove local copies from test files that define them.

**Verify:** `uv run pytest tests/ -q`

---

### Phase 8 — Verify

```bash
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/ -v
```

All 269 tests must pass. Ruff must show zero errors. Mypy errors should be zero or strictly reduced from baseline (3).

---

## Summary

| Phase | Items | Est. time |
|-------|-------|-----------|
| 1 — Deletions | J1, J2, H3 | 3 min |
| 2 — Bug fixes & hygiene | B1–B6, H1, H2, H4, H5, J3–J5, RF4, RF7 | 15 min |
| 3 — Configuration | CFG1, CFG2 | 5 min |
| 4 — Shared utils + dedup | RF1 | 30 min |
| 5 — Validation protocol | RF2 | 10 min |
| 6 — Repo standardization | RF3, RF4, RF6 | 15 min |
| 7 — Summaries + conftest | RF5, RF8 | 15 min |
| 8 — Verify | — | 5 min |
| **Total** | **20 items** | **~1.5 hr** |

Deferred items (DEF1–DEF5): opportunistically address when touching those files for other work.
