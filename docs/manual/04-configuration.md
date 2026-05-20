# 4. Configuration

Configuration is via a TOML file loaded from `./resemantica.toml` by default. Override with `--config PATH`.

## `[models]` — Model Allocation

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `translator_name` | string | `HY-MT1.5-7B` | Model name for Pass 1 translation |
| `preprocess_translator_names` | string list | `[]` | Models for preprocessing translation (falls back to `translator_name`) |
| `translator_context_window` | int | `null` | Override context window for translator |
| `translator_max_context_ratio` | float | `null` | Context ratio for translator (default 0.75 when `translator_context_window` set) |
| `analyst_name` | string | `Qwen3.5-9B-GLM5.1` | Model name for analysis/editing |
| `analyst_context_window` | int | `null` | Override context window for analyst |
| `analyst_max_context_ratio` | float | `null` | Context ratio for analyst |
| `eval_name` | string | `Qwen3.5-9B-GLM5.1` | Model for candidate evaluation |
| `embedding_name` | string | `BAAI/bge-m3` | Model for embedding/fuzzy matching. Auto-fetched from HuggingFace on first use and cached at `embedding/BAAI/bge-m3/`. Do not change unless you understand the embedding pipeline. |
| `pruning_threshold` | float | `0.3` | Min corpus score for glossary pruning |

## `[llm]` — LLM Server Connection

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `base_url` | string | `http://localhost:8080` | OpenAI-compatible API endpoint |
| `timeout_seconds` | int | `300` | Request timeout |
| `max_retries` | int | `2` | Retry count on transient failures |
| `context_window` | int | `65536` | Global context window (per-model overrides available) |
| `max_concurrent_requests_per_model` | int | `1` | Concurrency limit per model |

## `[paths]` — Storage Paths

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `artifact_root` | string | `artifacts` | Root directory for all outputs |
| `db_filename` | string | `resemantica.db` | SQLite database filename |

All actual paths are derived: `{artifact_root}/releases/{release_id}/...`

## `[budget]` — Token & Size Budgets

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_context_per_pass` | int | `49152` | Max tokens per translation pass |
| `max_paragraph_chars` | int | `2000` | Max characters per paragraph block |
| `max_bundle_bytes` | int | `4096` | Max bytes per paragraph bundle |
| `degrade_order` | string list | `["broad_continuity", "fuzzy_candidates", "rerank_depth", "pass3", "fallback_model"]` | Degradation order when context budget exceeded. See below for detailed behavior. |

### Degrade Order Behavior

When a chapter packet exceeds the token budget, the system iterates through `degrade_order` and clears the first available section, then retries:

| Key | What gets trimmed | Impact |
|-----|------------------|--------|
| `broad_continuity` | Broad story continuity context | Removes wide-context summary |
| `fuzzy_candidates` | Fuzzy alias/epithet candidates | Reduces entity matching quality |
| `rerank_depth` | Embedding reranker depth | Reduces alias disambiguation |
| `pass3` | Pass 3 readability polish | High-risk paragraphs skip polish |
| `fallback_model` | Fallback to simpler model | May reduce translation quality |

If all sections are cleared and budget is still exceeded, the packet build fails with `packet_budget_exceeded`.

## `[translation]` — Translation Behavior

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `pass3_default` | bool | `false` | Enable Pass 3 readability polish by default |
| `risk_threshold_high` | float | `0.7` | Paragraph risk score threshold (0.0–1.0). See below for risk formula. |

### Risk Classification Formula

Each paragraph is scored on a weighted formula (`translation/risk.py`):

```
risk_score = min(1.0,
    idiom_density * 0.20
    + title_density * 0.15
    + relationship_reveal * 0.20
    + pronoun_ambiguity * 0.20
    + xhtml_fragility * 0.15
    + entity_density * 0.10
)
```

Sub-scores:
- **idiom_density**: `min(1.0, idiom_count / 3.0)`
- **title_density**: `min(1.0, title_count / 3.0)`
- **relationship_reveal**: `1.0` if spoiler-sensitive relationship, else `0.0`
- **pronoun_ambiguity**: `min(1.0, ambiguous_pronoun_count / 2.0)` — counts he/she/it/they/him/her/them/his/its/their
- **xhtml_fragility**: `min(1.0, placeholder_count / 5.0)` — counts structural placeholders
- **entity_density**: `min(1.0, distinct_entity_count / 4.0)`

Risk classes: `HIGH` (>= `risk_threshold_high`, default 0.7), `MEDIUM` (>= 0.3), `LOW` (< 0.3). High-risk paragraphs get Pass 3 readability polish when `pass3_default` is enabled.
| `batched_model_order` | bool | `true` | Run all chapters pass1-first, then pass2 |
| `pass2_concurrency` | int | `2` | Concurrent Pass 2 jobs (must be >= 1) |

## `[batch_order]` — Batched Execution

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `true` | Enable batch ordering in production runs |
| `summary_chunk_multiplier` | int | `10` | Chapter chunk size multiplier for summaries |
| `translation_chunk_size` | int | `10` | Chapter chunk size for translation |

## `[summaries]` — Summary Generation

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `exclude_chapter_patterns` | string list | `[]` | Regex patterns for chapters to skip |
| `chapter_concurrency` | int | `1` | Concurrent summary generation (1–5) |
| `story_compact_max_tokens` | int | `2048` | Max tokens for compact story-so-far |
| `graph_continuity_rebase_interval` | int | `50` | Chapter interval for graph continuity rebase |

## `[events]` — Observability

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `persistence_mode` | string | `normal` | Event persistence: `normal` or `reduced` |
| `progress_sample_every` | int | `25` | Log one event per N progress updates |

## `[glossary]` — Glossary Discovery

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `min_term_length` | int | `2` | Minimum Chinese term length (chars) |
| `max_term_length` | int | `20` | Maximum Chinese term length (chars) |
| `min_corpus_score` | float | `0.1` | Minimum corpus frequency score |
| `eval_batch_size` | int | `50` | Batch size for LLM evaluation |
| `dedup_similarity_threshold` | float | `0.85` | Embedding similarity for alias dedup (0.0–1.0) |

## `[packets]` — Chapter Packet Assembly

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `budget_tokens` | int | `null` | Token budget override for packets |
| `max_bundle_bytes` | int | `4096` | Max bytes per paragraph bundle |
| `max_paragraph_chars` | int | `2000` | Max chars per paragraph block |

## Config Validation

The system validates configuration at startup (`settings.py:475-539`). Key rules:

| Setting | Constraint |
|---------|-----------|
| `translator_name`, `analyst_name`, `eval_name`, `embedding_name` | Must be non-empty strings |
| `max_context_per_pass`, `max_paragraph_chars`, `max_bundle_bytes` | Must be > 0 |
| `timeout_seconds` | Must be > 0 |
| `max_retries` | Must be >= 0 |
| `max_concurrent_requests_per_model` | Must be >= 1 |
| `risk_threshold_high` | Must be in [0.0, 1.0] |
| `persistence_mode` | Must be `"normal"` or `"reduced"` |
| `chapter_concurrency` | Must be in [1, 5] |
| `pass2_concurrency` | Must be >= 1 |
| `summary_chunk_multiplier`, `translation_chunk_size` | Must be > 0 |
| `story_compact_max_tokens`, `graph_continuity_rebase_interval` | Must be > 0 |
| `pruning_threshold` | Must be in [0.0, 1.0] |
| `progress_sample_every` | Must be > 0 |
| `glossary.min_term_length` | Must be >= 1 |
| `glossary.max_term_length` | Must be >= `min_term_length` |
| `glossary.min_corpus_score` | Must be >= 0 |
| `glossary.eval_batch_size` | Must be >= 1 |
| `glossary.dedup_similarity_threshold` | Must be in [0.0, 1.0] |
| `artifact_root`, `db_filename` | Must be non-empty |

### Effective Context Window

Per-model context windows are resolved in this priority:
1. Per-role override (`translator_context_window`, `analyst_context_window`)
2. Global `context_window` from `[llm]` section
3. Default (65536)

When a per-role window is set, `max_context_per_pass` is computed as `window * ratio` (default ratio: 0.75). Otherwise the global `max_context_per_pass` from `[budget]` is used.

## Configuration File Example

```toml
[llm]
base_url = "http://127.0.0.1:8080"
timeout_seconds = 1800
max_retries = 3
context_window = 65000

[models]
translator_name = "HY-MT1.5-7B"
analyst_name = "Qwen3.5-9B-GLM5.1"
embedding_name = "BAAI/bge-m3"

[paths]
artifact_root = "artifacts"
db_filename = "resemantica.db"

[budget]
max_context_per_pass = 49152
max_paragraph_chars = 2000
max_bundle_bytes = 4096

[translation]
pass3_default = false
risk_threshold_high = 0.7
batched_model_order = true
pass2_concurrency = 3

[summaries]
exclude_chapter_patterns = ["titlepage", "nav", "toc", "cover", "copyright"]
chapter_concurrency = 1
story_compact_max_tokens = 2048
```
