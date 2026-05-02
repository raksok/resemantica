# LLD 30: Per-Model Token Quotas

## Summary

Add per-model `context_window` and `max_context_per_pass` (derived as `context_window × ratio`) so the analyst model can use a larger budget than the translator. Parameterize budget helpers and the packet builder to accept model-specific overrides.

## Problem Statement

Currently `[llm] context_window` (default 65536) and `[budget] max_context_per_pass` (default 49152) are single global values. All models share the same budget — the analyst model's larger context window (240k) is wasted. Preprocessing stages (glossary, idioms, graph, summaries) call `chunk_text_for_prompt()` which splits source text into budget-safe chunks. With a global 49k budget, each long chapter requires 3-4x more LLM calls than necessary if the analyst could handle 180k chunks.

Additionally, packet builder `_apply_packet_budget()` degrades packet sections to fit the global budget. Building packets at the analyst budget would include more graph/summary context that could drown the source text signal during Pass 1 (translator). The packet budget must therefore be model-aware — translator gets lean packets, analyst gets rich context.

## Config Schema

### TOML (`[models]` section)

```toml
[models]
translator_name = "HY-MT1.5-7B"
translator_context_window = 65000          # optional, fallback → [llm] context_window
translator_max_context_ratio = 0.75        # optional, default 0.75
analyst_name = "Qwen3.5-9B-GLM5.1"
analyst_context_window = 240000            # optional
analyst_max_context_ratio = 0.75           # optional
embedding_name = "bge-M3"
```

Derivation when both per-model fields are set:

```
max_context_per_pass = max(global_max_context_per_pass, int(context_window × ratio))
```

The `max()` floor ensures the budget never drops below the global minimum, preventing accidental starvation from misconfiguration.

### `ModelsConfig` dataclass

```python
@dataclass(slots=True)
class ModelsConfig:
    translator_name: str = "HY-MT1.5-7B"
    translator_context_window: int | None = None
    translator_max_context_ratio: float | None = None
    analyst_name: str = "Qwen3.5-9B-GLM5.1"
    analyst_context_window: int | None = None
    analyst_max_context_ratio: float | None = None
    embedding_name: str = "bge-M3"
```

New `.toml` parsing in `load_config()`:

| TOML key | Type | Default | Field |
|---|---|---|---|
| `translator_context_window` | `int` | `None` | `ModelsConfig.translator_context_window` |
| `translator_max_context_ratio` | `float` | `None` | `ModelsConfig.translator_max_context_ratio` |
| `analyst_context_window` | `int` | `None` | `ModelsConfig.analyst_context_window` |
| `analyst_max_context_ratio` | `float` | `None` | `ModelsConfig.analyst_max_context_ratio` |

### Helper method

```python
def effective_max_context_per_pass(
    self, role: str, global_budget: int, global_window: int
) -> int:
    if role == "translator":
        window = self.translator_context_window or global_window
        ratio = self.translator_max_context_ratio or 0.75
    elif role == "analyst":
        window = self.analyst_context_window or global_window
        ratio = self.analyst_max_context_ratio or 0.75
    else:
        raise ValueError(f"Unknown role: {role}")
    return max(global_budget, int(window * ratio))
```

### Validation

Add to `validate_config()`:

```python
for role in ("translator", "analyst"):
    cw = getattr(config.models, f"{role}_context_window")
    if cw is not None and cw <= 0:
        raise ValueError(f"models.{role}_context_window must be > 0 when set")
    r = getattr(config.models, f"{role}_max_context_ratio")
    if r is not None and not (0 < r <= 1):
        raise ValueError(f"models.{role}_max_context_ratio must be in (0, 1] when set")
```

## Budget Helper Changes

### `ensure_prompt_within_budget`

```python
def ensure_prompt_within_budget(
    prompt: str,
    *,
    config: AppConfig,
    stage_name: str,
    chapter_number: int | None = None,
    max_tokens: int | None = None,
) -> int:
    token_count = count_tokens(prompt)
    limit = max_tokens if max_tokens is not None else config.budget.max_context_per_pass
    if token_count > limit:
        raise PromptBudgetError(
            stage_name=stage_name,
            chapter_number=chapter_number,
            token_count=token_count,
            max_tokens=limit,
        )
    return token_count
```

### `chunk_text_for_prompt`

```python
def chunk_text_for_prompt(
    text: str,
    *,
    config: AppConfig,
    static_prompt_tokens: int,
    max_tokens: int | None = None,
) -> list[TextChunk]:
    limit = max_tokens if max_tokens is not None else config.budget.max_context_per_pass
    max_text_tokens = limit - static_prompt_tokens
    # ... rest unchanged ...
```

### Error message clarity

`PromptBudgetError.__str__` currently shows `max_tokens=config.budget.max_context_per_pass`. Change to use the effective `limit`:

```python
def __str__(self) -> str:
    chapter = "" if self.chapter_number is None else f" chapter={self.chapter_number}"
    return (
        f"prompt_budget_exceeded: stage={self.stage_name}{chapter} "
        f"tokens={self.token_count} max={self.max_tokens}"
    )
```

This already uses `self.max_tokens` — no change needed since we pass the correct limit.

## Preprocessing Caller Changes

Each preprocessing pipeline that calls `ensure_prompt_within_budget` or `chunk_text_for_prompt` computes the analyst budget once and passes it as `max_tokens`. The pattern:

```python
# At pipeline entry:
analyst_budget = config_obj.models.effective_max_context_per_pass(
    "analyst", config_obj.budget.max_context_per_pass, config_obj.llm.context_window
)

# Then at each call site:
chunks = chunk_text_for_prompt(
    source_text,
    config=config_obj,
    static_prompt_tokens=count_tokens(static_prompt),
    max_tokens=analyst_budget,
)
```

### Changes per file

| File | Line(s) | Change |
|---|---|---|
| `graph/extractor.py` | 460, 489 | Compute `analyst_budget` at pipeline entry (around line 100). Pass to `chunk_text_for_prompt` and `ensure_prompt_within_budget`. |
| `idioms/extractor.py` | 198, 224 | Same — compute at entry, pass to both calls. |
| `glossary/discovery.py` | 189, 215 | Same — compute at entry, pass to both calls. |
| `summaries/generator.py` | 120, 141 | Same — compute at entry, pass to both calls. |
| `summaries/validators.py` | 211 | `ensure_prompt_within_budget` already receives `config` — compute budget at caller and pass as `max_tokens`. |

**No change to translation pipeline** (`translation/pipeline.py`, `pass2.py`, `pass3.py`) — these don't call budget helpers.

## Packet Builder Changes

### `_apply_packet_budget`

```python
def _apply_packet_budget(
    *,
    packet: ChapterPacket,
    config: AppConfig,
    budget_tokens: int | None = None,
) -> tuple[list[str], dict[str, dict[str, int]]]:
    effective_budget = budget_tokens if budget_tokens is not None else config.budget.max_context_per_pass
    # ... use effective_budget instead of config.budget.max_context_per_pass ...
```

### `build_chapter_packet`

```python
def build_chapter_packet(
    *,
    release_id: str,
    chapter_number: int,
    run_id: str = "packets-build",
    config: AppConfig | None = None,
    project_root: Path | None = None,
    graph_client: GraphClient | None = None,
    budget_tokens: int | None = None,
) -> PacketBuildOutput:
    # ...
    trimmed_sections, section_token_counts = _apply_packet_budget(
        packet=packet, config=config_obj, budget_tokens=budget_tokens
    )
```

### `build_packets`

```python
def build_packets(
    *,
    release_id: str,
    run_id: str = "packets-build",
    chapter_number: int | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    config: AppConfig | None = None,
    project_root: Path | None = None,
    graph_client: GraphClient | None = None,
    stop_token: StopToken | None = None,
    budget_tokens: int | None = None,
) -> dict[str, object]:
    # ...
    result = build_chapter_packet(
        # ...,
        budget_tokens=budget_tokens,
    )
```

## Orchestration Runner Changes

In `orchestration/runner.py` at the `packets-build` handler (line ~407):

```python
if stage_name == "packets-build":
    from resemantica.packets.builder import build_packets

    translator_budget = config.models.effective_max_context_per_pass(
        "translator", config.budget.max_context_per_pass, config.llm.context_window
    )
    packet_result = build_packets(
        release_id=self.release_id,
        run_id=self.run_id,
        config=self.config,
        chapter_number=chapter_number,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        stop_token=stop_token,
        budget_tokens=translator_budget,
    )
```

This ensures packets are trimmed for the translator model — graph context stays minimal, source text signal is preserved.

## TUI Settings Display

Add per-model context window rows to `_build_config_text()` in `tui/screens/settings.py`:

```python
lines.append("")
lines.append("[bold]Model Budgets[/bold]")
lines.append(
    f"  translator ctx: {config.models.effective_context_window('translator', config.llm.context_window)}"
)
lines.append(
    f"  analyst ctx:    {config.models.effective_context_window('analyst', config.llm.context_window)}"
)
```

This requires adding an `effective_context_window()` helper to `ModelsConfig` (mirroring the budget helper but returning just the window):

```python
def effective_context_window(self, role: str, global_window: int) -> int:
    if role == "translator":
        return self.translator_context_window or global_window
    elif role == "analyst":
        return self.analyst_context_window or global_window
    raise ValueError(f"Unknown role: {role}")
```

## Backward Compatibility

| Scenario | Behaviour |
|---|---|
| Config missing all per-model fields | Falls back to `[llm] context_window` and `[budget] max_context_per_pass` — identical to current behaviour. |
| Config sets only `analyst_context_window` | Analyst uses `int(240000 × 0.75) = 180000`. Translator uses global budget. |
| Config sets `analyst_context_window = 240000` and `analyst_max_context_ratio = 0.5` | Analyst gets `int(240000 × 0.5) = 120000`. |
| `budget_tokens` / `max_tokens` not passed to budget functions | Falls back to `config.budget.max_context_per_pass` — existing callers unchanged. |

## Error Scenarios

| Scenario | Behaviour |
|---|---|
| `translator_context_window = 0` | `validate_config()` raises `ValueError`. |
| `translator_max_context_ratio = 1.5` | `validate_config()` raises `ValueError` (> 1.0). |
| `translator_max_context_ratio = 0` | `validate_config()` raises `ValueError` (must be > 0). |
| Per-model `context_window` lower than `max_context_per_pass` | `max()` floor in `effective_max_context_per_pass` ensures at least `global_budget`. |

## Data Flow

```
User sets per-model context_window in TOML
  │
  ▼
load_config() → ModelsConfig fields populated
  │
  ├─► Preprocessing pipelines call:
  │     effective_max_context_per_pass("analyst", ...)
  │     → get 180000 for analyst
  │     → pass as max_tokens to ensure_prompt_within_budget
  │       and chunk_text_for_prompt
  │     → chapter text split into 180k chunks instead of 49k
  │     → 3.7× fewer LLM calls per chapter
  │
  └─► Orchestrator calls:
        effective_max_context_per_pass("translator", ...)
        → get 48750 for translator
        → pass as budget_tokens to build_packets
        → packet sections trimmed at translator-friendly budget
```

## Out Of Scope

- Per-model budget for Pass 2/3 prompt construction — these process one paragraph at a time and don't call budget helpers.
- Rebuilding packets per-pass — `build_packets` runs once with translator budget.
- Global `[budget] max_context_per_pass` removal — kept as minimum floor.
- Any rate-limiting, cost tracking, or usage capping based on per-model budgets.
- `embedding_name` model budget — embeddings are not LLM calls.
