# Task 30: Per-Model Token Quotas

## Goal

Allow each model (translator, analyst) to have its own `context_window` and `max_context_per_pass` derived as `context_window × ratio`, so the analyst can use a larger budget (~180k tokens) than the translator (~49k), reducing preprocessing LLM calls by processing longer chunks.

## Scope

In:

- Add optional `translator_context_window`, `translator_max_context_ratio`, `analyst_context_window`, `analyst_max_context_ratio` to `[models]` TOML section; fall back to global `[llm] context_window` and `[budget] max_context_per_pass` when absent.
- Extend `ModelsConfig` dataclass with new fields + helper `effective_max_context_per_pass(role, global_budget, global_window) -> int` that computes `int(context_window * ratio)`, floored at `global_budget`.
- Parameterize `ensure_prompt_within_budget()` and `chunk_text_for_prompt()` in `llm/budget.py` with an optional `max_tokens: int | None` override.
- Update 5 preprocessing pipelines to compute and pass the analyst budget as `max_tokens`:
  - `graph/extractor.py` (L460, L489)
  - `idioms/extractor.py` (L198, L224)
  - `glossary/discovery.py` (L189, L215)
  - `summaries/generator.py` (L120, L141)
  - `summaries/validators.py` (L211)
- Parameterize packet builder (`_apply_packet_budget`, `build_chapter_packet`, `build_packets`) with `budget_tokens: int | None`.
- In `orchestration/runner.py`, pass the **translator** budget to `build_packets` so packets stay lean for Pass 1.
- Update `tui/screens/settings.py` to display per-model `context_window`.
- Add per-model `context_window` entries (commented out) to `resemantica.toml` and `resemantica-pilot.toml`.

Out:

- Changing packet storage schema.
- Rebuilding packets per-pass — packet builder still runs once with translator budget.
- Adding per-model `context_window` to embedding model.
- Adding any rate-limiting or usage-capping logic.

## Owned Files Or Modules

- `src/resemantica/settings.py`
- `src/resemantica/llm/budget.py`
- `src/resemantica/packets/builder.py`
- `src/resemantica/orchestration/runner.py`
- `src/resemantica/graph/extractor.py`
- `src/resemantica/idioms/extractor.py`
- `src/resemantica/glossary/discovery.py`
- `src/resemantica/summaries/generator.py`
- `src/resemantica/summaries/validators.py`
- `src/resemantica/tui/screens/settings.py`
- `resemantica.toml`, `resemantica-pilot.toml`
- `docs/20-lld/lld-30-per-model-token-quotas.md`

## Interfaces To Satisfy

### `ModelsConfig.effective_max_context_per_pass`

```python
def effective_max_context_per_pass(self, role: str, global_budget: int, global_window: int) -> int:
    """Return max_context_per_pass for 'translator' or 'analyst' role.
    Falls back to global_budget if per-model context_window is not set.
    """
```

### `ensure_prompt_within_budget` / `chunk_text_for_prompt`

```python
def ensure_prompt_within_budget(
    prompt: str, *, config: AppConfig, stage_name: str,
    chapter_number: int | None = None, max_tokens: int | None = None,
) -> int: ...

def chunk_text_for_prompt(
    text: str, *, config: AppConfig, static_prompt_tokens: int,
    max_tokens: int | None = None,
) -> list[TextChunk]: ...
```

When `max_tokens` is not None, use it instead of `config.budget.max_context_per_pass`. Existing callers without `max_tokens` behave identically.

### Packet builder

```python
def _apply_packet_budget(*, packet: ChapterPacket, config: AppConfig, budget_tokens: int | None = None) -> ...
def build_chapter_packet(..., budget_tokens: int | None = None) -> PacketBuildOutput: ...
def build_packets(..., budget_tokens: int | None = None) -> dict[str, object]: ...
```

When `budget_tokens` is None, fall back to `config.budget.max_context_per_pass`.

### TOML schema

```toml
[models]
translator_name = "HY-MT1.5-7B"
translator_context_window = 65000
translator_max_context_ratio = 0.75
analyst_name = "Qwen3.5-9B-GLM5.1"
analyst_context_window = 240000
analyst_max_context_ratio = 0.75
embedding_name = "bge-M3"
```

Both `_context_window` and `_max_context_ratio` per model are optional. `_max_context_ratio` defaults to 0.75. `_context_window` defaults to `None` (use `[llm] context_window`).

## Tests Or Smoke Checks

- Unit: `effective_max_context_per_pass` returns correct values for per-model override, global fallback, and ratio customisation.
- Unit: `ensure_prompt_within_budget` uses `max_tokens` override when provided, falls back to `config.budget.max_context_per_pass` otherwise.
- Unit: `chunk_text_for_prompt` respects `max_tokens` override.
- Unit: `_apply_packet_budget` uses `budget_tokens` when provided.
- Existing tests pass: `uv run pytest tests/llm tests/glossary tests/summaries tests/idioms tests/graph tests/packets`.
- Run `uv run ruff check src tests`.

## Done Criteria

- `resemantica.toml` with per-model `context_window` applies different budgets to preprocessing vs translation.
- Analyst preprocessing stages receive up to ~180k tokens per chunk (vs 49k) when `analyst_context_window = 240000`.
- Packet builder uses translator budget, keeping packets lean for Pass 1.
- `max_context_ratio` is configurable per-model and defaults to 0.75.
- All existing tests pass; configs without per-model fields behave identically to before.
- TUI settings screen shows per-model `context_window`.
