# LLD 39: Deterministic Glossary Discovery

## Summary

Replace the LLM-first glossary candidate discovery in `glossary/discovery.py` with a deterministic NLP-first pipeline. HanLP provides Chinese word segmentation, POS tagging, and NER. Corpus-level statistics (TF-IDF, C-value) score candidates. Heuristic classifiers assign type priors. A deterministic prefilter rejects noise. The LLM role shifts from discoverer to batch evaluator — it judges a pre-screened candidate set instead of generating one from raw text. Embedding-based deduplication replaces the BGE-M3 common-word critic.

## Current State

```
[LLM discovery]         → analyst_name reads chapter text, emits JSON term list
[Deterministic filter]  → date patterns, stoplist (validators.py)
[BGE-M3 critic]         → cosine similarity pruning against common-word ref vocab
[DB upsert]             → glossary_candidates table + candidates.json artifact
```

Key problems:
- LLM is sole candidate source — misses are irrecoverable
- Non-deterministic: different runs produce different candidate sets
- No distributional signals (frequency, chapter coverage, TF-IDF)
- 360 lines of retry/cache/JSON-parse error handling for one LLM call
- Embedding critic does coarse common-word rejection, not semantic dedup

## Target State

```
[Stage 1: Deterministic candidate generation]
  HanLP segmentation + POS + NER
  Suffix/prefix pattern heuristics
  Webnovel seed dictionary lookup
  N-gram frequency extraction
       ↓
[Stage 2: Corpus statistics + scoring]
  TF-IDF across chapters
  C-value for multi-word terms
  Chapter document frequency
  Composite candidate score
       ↓
[Stage 3: Deterministic prefilter]
  Existing: date patterns, stoplist
  New: min/max length, punctuation/noise, common-word dictionary,
       POS-based generic rejection, score threshold
       ↓
[Stage 4: LLM batch evaluator]
  Batches of 50 candidates → analyst_name
  Schema-constrained JSON: keep/reject, type, reason_code, confidence
  Evidence snippets required per candidate
       ↓
[Stage 5: Embedding dedup / alias clustering]
  Embed candidates + context with embedding_name (configurable, default bge-M3)
  Cluster near-duplicates (segmentation variants, aliases)
  Compare against existing locked glossary
  Flag uncertain clusters for review
       ↓
[DB upsert + candidates.json]
```

## New Dependency

**HanLP**: `hanlp[full]>=2.1` — Chinese NLP pipeline providing tokenization, POS tagging, and NER in a single pass. The `[full]` extra includes the Multi-Task Learning model (~500MB download on first use). Runs on CPU, benefits from GPU.

Added to `pyproject.toml` as an optional dependency group `[project.optional-dependencies] nlp = ["hanlp[full]>=2.1"]` to keep base install lean. Pipeline falls back to a no-HanLP mode if unavailable (n-gram only, no POS/NER signals).

## Public Interfaces

CLI (unchanged commands, changed internal behavior):

- `rsem preprocess glossary-discover --release <release_id> [--pruning-threshold <float>]`

CLI (new flags):

- `--eval-batch-size <int>` — candidates per LLM evaluation batch (default 50)
- `--skip-llm-eval` — run deterministic stages only, skip LLM batch evaluation
- `--dedup-threshold <float>` — embedding similarity threshold for alias clustering (default 0.85)

Python modules (new):

- `glossary.segmenter` — HanLP integration
- `glossary.candidate_gen` — deterministic extraction strategies
- `glossary.corpus_stats` — TF-IDF / C-value / composite scoring
- `glossary.evaluator` — LLM batch evaluation

Python modules (modified):

- `glossary.discovery` — rewritten to orchestrate deterministic pipeline
- `glossary.validators` — expanded prefilter rules
- `glossary.critic` — rewritten for dedup/alias clustering
- `glossary.models` — extended `GlossaryCandidate` with NLP feature fields
- `glossary.pipeline` — updated to wire new stages
- `db.glossary_repo` — new columns in upsert/read
- `db.sqlite` — schema evolution for new columns
- `settings` — new `GlossaryConfig` section

## Module Contracts

### `glossary/segmenter.py`

```python
@dataclass(slots=True)
class SegmentedToken:
    text: str
    pos: str          # HanLP CTB POS tag (NR, NN, VV, etc.)
    ner: str | None    # NER label (PERSON, LOC, ORG, MISC) or None
    offset_start: int  # character offset in source
    offset_end: int

def segment_chapter(source_text: str) -> list[SegmentedToken]:
    """
    Run HanLP tokenization + POS + NER on source text.
    Lazy-loads the HanLP pipeline on first call.
    Returns flat token list with POS and NER annotations.
    Falls back to character-level iteration if HanLP is unavailable.
    """
```

Design notes:
- HanLP MTL pipeline loaded once, cached in module-level global
- Warmup takes ~10s; subsequent chapters are fast
- POS tags follow CTB (Chinese Treebank) tagset: NR (proper noun), NN (common noun), VV (verb), etc.
- NER labels: PERSON, LOC, ORG, MISC — mapped to glossary categories

### `glossary/candidate_gen.py`

```python
@dataclass(slots=True)
class RawCandidate:
    surface: str                             # exact text as found
    normalized: str                          # normalized via existing normalize_term()
    source_strategies: list[str]             # e.g. ["ner_person", "suffix_faction", "ngram"]
    pos_tags: list[str]                      # POS sequence of constituent tokens
    ner_label: str | None                    # NER label if NER-sourced
    type_prior: str | None                   # heuristic category (character, faction, etc.)
    chapter_occurrences: dict[int, int]      # {chapter_number: count}
    first_occurrence_offset: int             # char offset in first-seen chapter
    context_snippets: list[str]              # up to 3 representative snippets (~60 chars each)

def generate_candidates_for_chapter(
    chapter_number: int,
    tokens: list[SegmentedToken],
    source_text: str,
    *,
    webnovel_dict: set[str] | None = None,
) -> list[RawCandidate]:
    """
    Run all extraction strategies on one chapter's tokens.
    
    Strategies:
    1. NER entities — PERSON→character, LOC→location, ORG→faction
    2. POS-based noun phrases — sequences of NR, NNP tokens
    3. Suffix/prefix patterns:
       - Surnames (百家姓 list) + 1-2 chars → character candidate
       - 门/派/宗/教/盟 suffixes → faction
       - 山/城/谷/洞/殿/阁/院/湖/海/河 suffixes → location  
       - 术/法/功/诀/拳/掌/剑/刀 suffixes → technique
       - 丹/丸/药/甲/剑/刀/戒/镜 suffixes → item_artifact
       - 境/层/阶/级/期/重/品 suffixes → realm_concept
    4. Webnovel seed dictionary exact-match
    5. N-gram extraction (2-6 chars) with min frequency threshold
    
    Deduplication: same normalized form from multiple strategies
    merges into one RawCandidate with combined source_strategies.
    """
```

### `glossary/corpus_stats.py`

```python
@dataclass(slots=True)
class CorpusStats:
    term_frequency: dict[str, int]       # total occurrences across corpus
    document_frequency: dict[str, int]   # chapters containing term
    total_chapters: int
    total_tokens: int

@dataclass(slots=True)
class ScoredCandidate:
    raw: RawCandidate
    tf_idf: float       # term frequency × inverse document frequency
    c_value: float      # for multi-token terms: log2(|term|) × freq - Σ(freq of superstrings) / count(superstrings)
    composite_score: float  # weighted combination

def compute_corpus_stats(
    per_chapter_candidates: dict[int, list[RawCandidate]],
) -> CorpusStats:
    """Aggregate per-chapter candidate occurrences into corpus-level counts."""

def score_candidates(
    candidates: list[RawCandidate],
    stats: CorpusStats,
) -> list[ScoredCandidate]:
    """
    Compute TF-IDF and C-value for each candidate.
    
    Composite score formula:
      composite = 0.3 * norm_tf_idf + 0.3 * norm_c_value + 0.2 * strategy_count + 0.2 * coverage_ratio
    
    where:
      norm_tf_idf = tf_idf / max(tf_idf across all candidates)
      norm_c_value = c_value / max(c_value) for len >= 2, else 0
      strategy_count = len(source_strategies) / max_strategies
      coverage_ratio = document_frequency / total_chapters
    """
```

### `glossary/evaluator.py`

```python
@dataclass(slots=True)
class EvalResult:
    candidate_id: str
    keep: bool
    term_type: str        # from GlossaryCategory enum
    reason_code: str      # structured: "proper_noun", "setting_term", "common_word", "date_time", "generic_noun", "ambiguous"
    confidence: float     # [0.0, 1.0]

def evaluate_candidate_batch(
    *,
    candidates: list[GlossaryCandidate],
    llm_client: LLMClient,
    model_name: str,
    prompt_template: str,
    prompt_version: str,
    batch_size: int = 50,
    config: AppConfig | None = None,
    cache_root: Path | None = None,
    event_callback: Callable | None = None,
    stop_token: StopToken | None = None,
) -> list[EvalResult]:
    """
    Batch candidates for LLM keep/reject evaluation.
    
    Per batch:
    1. Format candidates as JSON array with: surface, context_snippets,
       frequency, chapter_coverage, type_prior
    2. Render prompt template with candidate JSON
    3. Call LLM, parse schema-constrained JSON response
    4. Cache by batch content hash (not chapter hash)
    
    Error handling: per-batch try/except, skip failed batches.
    """
```

### Prompt: `llm/prompts/glossary_evaluate.txt`

```text
# version: 1.0

## TASK
GLOSSARY_EVALUATE

## CANDIDATES
{CANDIDATES_JSON}

## INSTRUCTIONS
You are evaluating candidate terms extracted from a Chinese web novel (玄幻/仙侠 genre).
For each candidate, decide if it is a genuine glossary-worthy term that requires
consistent translation across the novel.

Glossary-worthy terms include: character names, aliases, titles/honorifics,
faction/sect/clan names, location names, martial techniques, items/artifacts,
cultivation realm concepts, creature/race names, and named events.

NOT glossary-worthy: common words, generic nouns, dates/times, function words,
generic verbs, common adjectives, measurement units, body parts.

For each candidate, return:
- candidate_id: the provided ID (string)
- keep: true if glossary-worthy, false otherwise (boolean)
- term_type: one of [character, alias, title_honorific, faction, location, technique, item_artifact, realm_concept, creature_race, generic_role, event, idiom]
- reason_code: one of [proper_noun, setting_term, cultivation_term, common_word, date_time, generic_noun, generic_verb, ambiguous, insufficient_evidence]
- confidence: 0.0 to 1.0 (float)

## OUTPUT FORMAT
Return a JSON array only. No markdown fences. No explanation text.
Each element: {"candidate_id": "...", "keep": true/false, "term_type": "...", "reason_code": "...", "confidence": 0.9}
If you cannot evaluate a candidate, set keep=false, reason_code="ambiguous", confidence=0.0.
```

### Expanded `glossary/validators.py`

New rejection rules added to `apply_deterministic_filter()`:

| Rule | Rejection Condition | Filter Reason |
|------|-------------------|---------------|
| min_length | `len(source_term) < config.glossary.min_term_length` | `min_length` |
| max_length | `len(source_term) > config.glossary.max_term_length` | `max_length` |
| punctuation_noise | term is only punctuation, digits, or whitespace | `punctuation_noise` |
| common_word_dict | exact match in `data/common_words.txt` | `common_word` |
| pos_generic | POS sequence is pure VV/AD/P/CC (verb/adverb/prep/conj) | `pos_generic` |
| score_threshold | `composite_score < config.glossary.min_corpus_score` | `low_score` |

Existing rules preserved: `date_pattern`, `stop_list`.

### `glossary/data/` directory

New data files shipped with the package:

| File | Purpose | Size |
|------|---------|------|
| `common_words.txt` | High-frequency common words, one per line | ~5000 entries |
| `webnovel_dict.txt` | Seed dictionary of common xianxia/wuxia terms | ~500 entries |
| `surnames.txt` | Chinese surname list (百家姓) | ~500 entries |

Loaded once at pipeline init via `importlib.resources` or `pathlib` relative to package.

### Rewritten `glossary/critic.py`

The BGE-M3 common-word critic is replaced with embedding-based deduplication and alias clustering.

```python
@dataclass(slots=True)
class AliasCluster:
    canonical_id: str
    canonical_term: str
    aliases: list[str]
    member_ids: list[str]
    similarity_score: float
    existing_glossary_match: str | None  # locked entry ID if found

def deduplicate_and_cluster(
    candidates: list[GlossaryCandidate],
    *,
    model_name: str,             # from config.models.embedding_name
    existing_entries: list[LockedGlossaryEntry] | None = None,
    similarity_threshold: float = 0.85,
) -> tuple[list[GlossaryCandidate], list[AliasCluster]]:
    """
    1. Embed each candidate as "{surface} [{category}] {context_snippet}"
    2. Compute pairwise cosine similarity
    3. Union-Find clustering: merge pairs above similarity_threshold
    4. For each cluster: pick highest-scored candidate as canonical,
       mark others as aliases (candidate_status = "alias_merged")
    5. Compare canonical terms against existing_entries embeddings
       to flag re-discoveries of already-locked terms
    6. Return (deduplicated_candidates, alias_clusters)
    """
```

Model: uses `config.models.embedding_name` (default `bge-M3`, same as current). The embedding model is configurable — if upgraded to a larger model later, only config changes.

### Extended `GlossaryCandidate` model

New fields appended to the dataclass (all nullable, backward compatible):

```python
# NLP feature fields (populated by deterministic pipeline)
pos_tags: str | None = None              # JSON-encoded list of POS tags
ner_label: str | None = None             # HanLP NER label
type_prior: str | None = None            # heuristic category guess
source_strategies: str | None = None     # JSON-encoded list of strategy names
chapter_coverage: int | None = None      # number of chapters containing term
corpus_score: float | None = None        # composite TF-IDF/C-value score
context_snippets: str | None = None      # JSON-encoded list of snippets

# LLM evaluator fields (populated by Stage 4)
llm_keep: int | None = None              # 1=keep, 0=reject (SQLite boolean)
llm_type: str | None = None              # LLM-assigned category
llm_reason_code: str | None = None       # structured reason code
llm_confidence: float | None = None      # LLM confidence [0, 1]
```

Note: list fields stored as JSON strings in SQLite (TEXT columns). Parsed by `_candidate_from_row()` helper.

### Schema Evolution

New columns added to `glossary_candidates` table:

```sql
ALTER TABLE glossary_candidates ADD COLUMN pos_tags TEXT;
ALTER TABLE glossary_candidates ADD COLUMN ner_label TEXT;
ALTER TABLE glossary_candidates ADD COLUMN type_prior TEXT;
ALTER TABLE glossary_candidates ADD COLUMN source_strategies TEXT;
ALTER TABLE glossary_candidates ADD COLUMN chapter_coverage INTEGER;
ALTER TABLE glossary_candidates ADD COLUMN corpus_score REAL;
ALTER TABLE glossary_candidates ADD COLUMN context_snippets TEXT;
ALTER TABLE glossary_candidates ADD COLUMN llm_keep INTEGER;
ALTER TABLE glossary_candidates ADD COLUMN llm_type TEXT;
ALTER TABLE glossary_candidates ADD COLUMN llm_reason_code TEXT;
ALTER TABLE glossary_candidates ADD COLUMN llm_confidence REAL;
```

All nullable — existing rows unaffected. Applied via `ensure_schema()` using `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern (or try/except on OperationalError for SQLite < 3.35).

New table for alias clusters:

```sql
CREATE TABLE IF NOT EXISTS glossary_alias_clusters (
    cluster_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    canonical_candidate_id TEXT NOT NULL,
    canonical_term TEXT NOT NULL,
    aliases_json TEXT NOT NULL,           -- JSON array of alias surface forms
    member_ids_json TEXT NOT NULL,        -- JSON array of candidate IDs in cluster
    similarity_score REAL NOT NULL,
    existing_glossary_match TEXT,         -- locked_glossary entry ID if found
    discovery_run_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (release_id, canonical_candidate_id)
);
```

### Configuration: `GlossaryConfig`

```toml
[glossary]
min_term_length = 2
max_term_length = 20
min_corpus_score = 0.1
eval_batch_size = 50
dedup_similarity_threshold = 0.85
```

Added to `settings.py` as `GlossaryConfig` dataclass, nested under `AppConfig.glossary`.

## Data Flow (Detailed)

```
for chapter_ref in chapter_refs:
    payload = load_chapter_json(chapter_ref)
    source_text = collect_source_text(payload)
    tokens = segment_chapter(source_text)              ← segmenter.py
    raw = generate_candidates_for_chapter(              ← candidate_gen.py
        chapter_number, tokens, source_text,
        webnovel_dict=webnovel_dict
    )
    per_chapter[chapter_number] = raw

stats = compute_corpus_stats(per_chapter)               ← corpus_stats.py
scored = score_candidates(all_candidates, stats)         ← corpus_stats.py

candidates = convert_to_glossary_candidates(scored)      ← discovery.py
candidates = apply_deterministic_filter(candidates)      ← validators.py (expanded)

if not skip_llm_eval:
    eval_results = evaluate_candidate_batch(             ← evaluator.py
        candidates=active_candidates,
        llm_client=client,
        model_name=config.models.analyst_name,
    )
    candidates = apply_eval_results(candidates, eval_results)

candidates, clusters = deduplicate_and_cluster(          ← critic.py (rewritten)
    candidates,
    model_name=config.models.embedding_name,
    existing_entries=locked_entries,
)

upsert_discovered_candidates(conn, candidates=candidates)
upsert_alias_clusters(conn, clusters=clusters)
```

## Candidate Status Lifecycle (Updated)

```
raw_candidate → discovered     (after corpus scoring)
             → filtered        (deterministic prefilter)
             → llm_rejected    (LLM evaluator: keep=false)  ← NEW
             → alias_merged    (dedup: merged into canonical) ← NEW
             → pruned          (dedup: below similarity threshold or flagged)
             → translated      (survived all stages, LLM translation)
             → conflict        (promotion validation failed)
             → promoted        (locked glossary)
```

New statuses: `llm_rejected`, `alias_merged`. Added to `CandidateStatus` literal type.

## Cache Invalidation

- Existing `glossary.discover` LLM cache (keyed on chapter source hash) becomes stale. Note: leave old cache files; they won't be read because the discovery path no longer makes those LLM calls.
- New cache entries for `glossary.evaluate` stage keyed on batch content hash + prompt version.
- HanLP segmentation results are not cached (fast enough on CPU, ~2s per chapter).

## Backward Compatibility

- `discover_glossary_candidates()` pipeline function: signature unchanged externally (same params accepted). Internal behavior changed.
- Translate, promote, and review stages: **completely unchanged**. They consume `GlossaryCandidate` objects as before.
- New nullable columns don't break existing DB reads — `_candidate_from_row()` handles None gracefully.
- `--skip-llm-eval` flag allows running deterministic stages only for debugging.

## Tests

- `test_segmenter.py` — mock HanLP, verify SegmentedToken output
- `test_candidate_gen.py` — each extraction strategy with fixture Chinese text
- `test_corpus_stats.py` — TF-IDF/C-value with known input/output
- `test_evaluator.py` — mock LLM, verify batch construction and JSON parsing
- `test_critic_dedup.py` — mock embeddings, verify clustering
- `test_validators_expanded.py` — all new filter rules
- `test_glossary_pipeline.py` — integration: mock HanLP + LLM, verify end-to-end
- `test_schema_migration.py` — ALTER TABLE on existing DB doesn't lose data
- Existing tests in `tests/glossary/` must still pass

## Summary → Glossary Interface (Added in Task 44)

### Motivation

The summaries stage runs first and produces structured per-chapter data (`new_terms`, `characters_mentioned`, `key_events`, `setting`). The glossary stage previously consumed only the `is_story_chapter` boolean flag. Passing summary content into glossary extraction improves precision (terms the LLM explicitly flagged as "new" are high-confidence), reduces noise (summary-verified terms get a score boost), and provides category hints (characters vs. locations).

### Data Flow

```
summaries pipeline:
  summary_drafts.content_json  ──►  per-chapter dict with:
                                       new_terms: ["青云门", "张三", ...]
                                       characters_mentioned: ["张三", "李四", ...]
                                       key_events: [...]
                                       setting: "..."
                                              │
                                              ▼
glossary pipeline (pipeline.py):
  query summary_drafts ──► chapter_summaries: dict[int, dict]
                                              │
                                              ▼
discovery.py:  accept chapter_summaries
              │         │
              ▼         ▼
  candidate_gen.py    corpus_stats.py
  extract_summary_    score_candidates()
  terms() → seeds     → 1.15× multiplier if
  with "from_summary"    term in summary_terms
  strategy               (new_terms ∪ chars_mentioned)
```

### Modified Modules

#### `glossary/pipeline.py`

```python
# New query block in discover_glossary_candidates():
chapter_summaries: dict[int, dict] = {}
try:
    cursor = conn.execute(
        "SELECT chapter_number, content_json FROM summary_drafts "
        "WHERE release_id = ? AND summary_type = 'chapter_summary_zh_structured'"
        "  AND validation_status IN ('approved', 'pending', 'non_story_chapter')",
        (release_id,),
    )
    for row in cursor.fetchall():
        ch = int(row[0])
        raw = json.loads(row[1])
        content = raw.get("parsed_summary", raw)  # unwrap validation-failure wrapper
        chapter_summaries[ch] = content
except Exception:
    pass  # table may not exist
```

Passed to `discover_candidates_from_extracted()` as `chapter_summaries=chapter_summaries`.

#### `glossary/discovery.py`

```python
def discover_candidates_from_extracted(
    *,
    ...
    chapter_summaries: dict[int, dict] | None = None,
) -> list[GlossaryCandidate]:
```

- Passes per-chapter summary data to `generate_chapter_candidates(text, summary_data=summary_data)`.
- Builds `summary_term_set: set[str]` from all chapters' `new_terms ∪ characters_mentioned`.
- Passes to `score_candidates(candidates, stats, summary_term_set=summary_term_set)`.
- Exempts summary-seeded terms from the `df >= 2` pre-filter.

#### `glossary/candidate_gen.py`

New extraction strategy:

```python
def extract_summary_terms(summary_data: dict | None) -> list[RawCandidate]:
    """Seed candidates from summary new_terms, with category hints."""
    if not summary_data:
        return []
    chars = set(summary_data.get("characters_mentioned", []))
    setting = summary_data.get("setting", "")
    candidates = []
    for term in summary_data.get("new_terms", []):
        if len(term) < 2:
            continue
        type_prior = CAT_OTHER
        if term in chars:
            type_prior = CAT_CHARACTER
        elif setting and term in setting:
            type_prior = CAT_LOCATION
        candidates.append(RawCandidate(
            surface_form=term,
            normalized_form=term,
            pos_tags=[],
            ner_label=None,
            type_prior=type_prior,
            strategies={"from_summary"},
            context_snippets=[],
        ))
    return candidates
```

Category hint rules: only overrides `CAT_OTHER` (if extraction strategies disagree, the higher-priority type wins via `merge_candidates` type_priority dict). Called in `generate_chapter_candidates()` alongside NER/POS/heuristic/dict/ngram.

#### `glossary/corpus_stats.py`

```python
def score_candidates(
    candidates: list[RawCandidate],
    stats: CorpusStats,
    summary_term_set: set[str] | None = None,
) -> list[ScoredCandidate]:
```

- After the strategy multiplier block, applies a 1.15× multiplier if `c.normalized_form in summary_term_set`.
- The `from_summary` strategy also contributes to `strategy_count` (0.2 weight in composite).

### Graceful Degradation

Every summary-aware parameter defaults to `None`. If `summary_drafts` table doesn't exist (summaries never ran), all try/except catches → `chapter_summaries = {}` → no seed candidates, no boost → identical behavior to pre-Task-44.

### Updated Data Flow Diagram

```
[Stage 0: Query summary data]
  Read summary_drafts.content_json for each chapter
       ↓
[Stage 1: Deterministic candidate generation]
  HanLP segmentation + POS + NER
  Suffix/prefix pattern heuristics
  Webnovel seed dictionary lookup
  N-gram frequency extraction
  Summary new_terms seed candidates     ← NEW
       ↓
[Stage 2: Corpus statistics + scoring]
  TF-IDF across chapters
  C-value for multi-word terms
  Chapter document frequency
  Composite candidate score
  Summary-verified term boost (1.15×)    ← NEW
       ↓
[Stage 3: Deterministic prefilter]
  ... (unchanged)
       ↓
[Stage 4: LLM batch evaluator]
  ... (unchanged)
       ↓
[Stage 5: Embedding dedup / alias clustering]
  ... (unchanged)
       ↓
[DB upsert + candidates.json]
```

### Tests (New)

- `test_candidate_gen.py`: test `extract_summary_terms` with empty data, new_terms list, character cross-reference, setting cross-reference, single-character filter.
- `test_corpus_stats.py`: verify summary-verified candidate gets higher composite score than non-verified candidate with identical features.
- `test_glossary_pipeline.py`: integration test with mocked summary data verifying skip+seed flow.

## Out Of Scope

- Summary generation
- Graph alias resolution
- Translation pipeline changes
- TUI changes
- Prompt changes for `glossary_translate.txt` (Stage B is untouched)
- Webnovel dictionary curation (ship seed, iterate later)
