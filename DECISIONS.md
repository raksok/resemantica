# Resemantica Architecture and Implementation Decisions

Version: 1.0
Date: 2026-04-23
Status: Active
Source: Gap analysis and brainstorming session covering all documentation

This document records the decisions made to resolve gaps identified across SPEC.md, ARCHITECT.md, DATA_CONTRACT.md, and the docs/ tree. Each decision includes what was decided, alternatives considered, and the rationale.

---

## A. Foundational Decisions

### A1. Configuration Schema

**Decision:** Use TOML format with `resemantica.toml` in project root. Plain dataclasses with manual validation for config loading. Define full schema upfront but fill fields incrementally per milestone.

**Config file:** `resemantica.toml` in project root.

**Default structure:**

```toml
[models]
translator_name = "HY-MT1.5-7B"
analyst_name = "Qwen3.5-9B-GLM5.1"
embedding_name = "bge-M3"

[llm]
base_url = "http://localhost:8080"
timeout_seconds = 300
max_retries = 2
context_window = 65536

[paths]
artifact_root = "artifacts"
db_filename = "resemantica.db"

[budget]
max_context_per_pass = 49152
max_paragraph_chars = 2000
max_bundle_bytes = 4096
degrade_order = [
    "broad_continuity",
    "fuzzy_candidates",
    "rerank_depth",
    "pass3",
    "fallback_model",
]

[translation]
pass3_default = true
risk_threshold_high = 0.7
```

**Default model note:**

- `translator_name` defaults to `HY-MT1.5-7B`
- `analyst_name` defaults to `Qwen3.5-9B-GLM5.1`
- `embedding_name` defaults to `bge-M3`
- `Qwen3.5-9B-GLM5.1` refers to the Qwen3.5-base distilled GLM5.1 variant from jackrong on Hugging Face

**Alternatives considered:**
- YAML: requires PyYAML dependency
- Python dataclass + file overlay: harder to inspect without running code
- Pydantic + TOML: adds dependency for a CLI tool

**Rationale:** TOML is Python stdlib (3.11+), version-control friendly, and easy to validate. Plain dataclasses avoid heavy dependencies. Full schema with incremental fill prevents config drift while staying practical.

---

### A2. Source Text Segmentation and Block Definition

**Decision:**

- A block is a leaf-level XHTML text element: `<p>`, `<h1>`-`<h6>`, text-containing `<div>`, `<li>`, `<td>`, and similar.
- Non-text elements (images, rules, tables) become blocks with placeholder treatment.
- Maximum block size is approximately 1500 characters. Blocks exceeding this are split at sentence boundaries.
- Block ID format: `ch{NNN}_blk{NNN}` (e.g., `ch003_blk007`).
- Segment ID format: when a block is split, segments receive `ch{NNN}_blk{NNN}_seg{NN}` (e.g., `ch001_blk010_seg01`). Unsplit blocks have no segment suffix. Segments carry `parent_block_id` for reconstruction.

**Alternatives considered:**
- Strict paragraph/heading only: misses content in `<div>`, `<li>`, `<td>`.
- Sentence-level splitting: finer granularity but harder to maintain coherence.
- No splitting: risks exceeding context budget.

**Rationale:** Leaf-element blocks match the natural translation unit in Chinese web novels. The 1500-char limit with sentence-boundary splitting prevents context overflow while preserving coherence. The `ch{NNN}_blk{NNN}` format is human-readable and stable across reruns.

---

### A3. Placeholder System

**Decision:**

- Inline formatting elements (`<i>`, `<b>`, `<em>`, `<span>`, `<a>`, `<u>`, `<s>`) and block elements (`<img>`, `<hr>`, `<div>`, `<table>`, `<ruby>`, `<br>`) are replaced with placeholders during translation.
- Placeholder syntax: `⟦TYPE_N⟧` for opening tags and `⟦/TYPE_N⟧` for closing tags, using Unicode brackets (U+27E6, U+27E7).
- Explicit type codes: B (bold/strong), I (italic/em), U (underline), S (strikethrough), SPAN, IMG, HR, DIV, RUBY, A (link), TABLE, BR.
- The placeholder map stores the original element and its attributes for reversible restoration.
- N is a sequential integer within the block, resetting per block.
- **Both opening and closing placeholders appear in the extracted text** sent to the model. The model sees `⟦B_1⟧⟦I_1⟧text⟦/I_1⟧⟦/B_1⟧` and is expected to preserve them in translation output.

**Closing placeholder convention:**

- Closing tags are emitted as `⟦/TYPE_N⟧` where `TYPE_N` matches the corresponding opening placeholder exactly.
- The restorer maps each `⟦/TYPE_N⟧` to its opening entry's `element` field and emits `</element>`.
- The `closing_order` array on the outermost parent is a **validation** field. After restoration, the restorer checks that closing placeholders appear in the documented order (innermost first). If the model reorders closing placeholders, the restorer warns and applies the correct order from `closing_order`.
- Self-closing elements (`<img>`, `<hr>`, `<br>`) have no closing placeholder.

**Nested tag handling:**

When tags are nested (e.g., `<b><i>text</i></b>`), each inner tag gets its own pair of opening/closing placeholders:

```json
{
  "placeholder": "⟦I_1⟧",
  "element": "i",
  "attributes": {},
  "parent_placeholder": "⟦B_1⟧",
  "depth": 2,
  "closing_order": null
}
```

The outermost parent entry:

```json
{
  "placeholder": "⟦B_1⟧",
  "element": "b",
  "attributes": {},
  "parent_placeholder": null,
  "depth": 1,
  "closing_order": ["⟦I_1⟧", "⟦B_1⟧"]
}
```

Rules for nested placeholders:

- Inner tags receive their own `⟦TYPE_N⟧` / `⟦/TYPE_N⟧` pair.
- Each nested entry records its `parent_placeholder` (or null if top-level).
- The `closing_order` array on the **outermost** parent lists all nested placeholders in reverse opening order (innermost closes first) — used for post-restoration validation, not as the primary restoration mechanism.
- Restoration converts each opening placeholder to its `original_xhtml` and each closing placeholder to `</element>`. The restorer does not guess closing order.
- Deep nesting (depth > 3) is flattened to the outermost tag only, with inner tags recorded in the map for manual inspection but not rendered as separate placeholders in the text sent to the model.

**Alternatives considered:**

- `[[TYPE_N]]` ASCII brackets: could collide with Chinese bracket usage in source text.
- `<PH_TYPE_N/>` XML-like: may confuse the model into treating it as HTML.
- Single flat placeholder for nested tags: loses restoration fidelity for legitimate formatting.
- Implicit closing tags (no `⟦/TYPE_N⟧`): restorer must infer where translated text ends, fragile for multi-segment blocks.

**Rationale:** Unicode brackets are visually distinct and extremely unlikely to appear in Chinese web novel text. Explicit type codes give the model context about what each placeholder represents, improving translation quality. Explicit closing placeholders make restoration deterministic — the restorer performs a simple lookup, not inference. Stack-ordered `closing_order` provides validation against model reordering without being the primary restoration mechanism.

---

### A4. SQLite Foundation

**Decision:**

- Database file: `artifacts/resemantica.db` (one DB per project).
- **WAL (Write-Ahead Logging) mode is mandatory.** Every connection must execute `PRAGMA journal_mode=WAL;` on open. This prevents `Database is locked` errors when the TUI (M12) reads while the orchestrator writes concurrently.
- Schema migration: manual version-numbered scripts in `db/migrations/`.
- Repository pattern: per-domain repository classes (glossary_repo, summary_repo, etc.) sharing a SQLite connection.

**Alternatives considered:**
- Per-release database: harder cross-release queries.
- Alembic: mature but adds SQLAlchemy dependency.
- Auto-create on startup: no migration path for schema changes.
- Default rollback journal: causes `Database is locked` under concurrent read/write (TUI + orchestrator).

**Rationale:** One project-level DB simplifies queries and cleanup. Manual migrations are sufficient for a local-first CLI tool. WAL mode is essential because M12 (TUI) will read the database while M10 (orchestrator) writes checkpoints and events; without WAL, SQLite blocks concurrent readers.

---

### A5. Test Strategy

**Decision:**

- Framework: pytest.
- Layout: `tests/` directory mirroring `src/` (e.g., `tests/epub/test_extractor.py`).
- External dependency mocking:
  - Fixture EPUB for epub tests.
  - Mocked LLM client for translation/preprocessing tests.
  - In-memory SQLite for DB tests.
  - LadybugDB tests deferred to M6 with integration marks.
- Test discovery: `pytest tests/` from project root.

**Alternatives considered:**
- unittest stdlib: less ergonomic.
- All mocks: won't catch integration issues.
- Full integration: hard to run without real services.

**Rationale:** pytest is the de facto standard. The mirror layout makes it easy to find tests. Fixture EPUB + mocked LLM + in-memory SQLite gives reliable, fast tests without external dependencies.

---

## B. LLM Integration Decisions

### B6. llama.cpp Client Interface

**Decision:**

- Use llama.cpp server in **router mode** with a single `base_url`.
- The config maps model role names (`translator_name`, `analyst_name`, `embedding_name`) to model identifiers that llama.cpp router recognizes.
- Our client sends standard OpenAI-style requests with `model=<model_name>` and llama.cpp router handles model loading.
- Use the **`openai` Python package** as the HTTP client library.
- Rich client with streaming support, token counting, and structured output parsing.
- No conversation memory management in the client layer (context is managed through packets/bundles).

**Alternatives considered:**
- llama-cpp-python bindings: ties inference to Python process, GIL issues, harder to swap models.
- Raw httpx/requests: reinvent request formatting and retry logic.
- Third-party LLM orchestration wrapper: heavy dependency for simple HTTP calls.

**Rationale:** Router mode eliminates the need to manage multiple server instances. The `openai` package gives us structured completions, error handling, and streaming for free. A rich client with token counting and structured output parsing supports the pipeline needs without over-engineering.

---

### B7. Prompt Management

**Decision:**

- Prompt templates stored as text files in `src/resemantica/llm/prompts/`.
- Each file has an inline version comment: `# version: 1.0`.
- The prompt loader reads the file and exposes the version to callers for checkpoint/reproducibility.

**File naming convention:**

```
src/resemantica/llm/prompts/
  translate_pass1.txt
  translate_pass2.txt
  translate_pass3.txt
  glossary_discover.txt
  glossary_translate.txt
  summary_zh_structured.txt
  summary_zh_short.txt
  summary_en_derive.txt
  summary_validate.txt
  idiom_detect.txt
  entity_extract.txt
  relationship_extract.txt
  translate_with_context.txt       # Template B
  translate_with_term.txt           # Template C
  translate_with_term_and_context.txt # Template D
```

**Alternatives considered:**
- SQLite with versioning: harder to edit and version control.
- In config file: makes config huge.
- Separate manifest: extra file to maintain.

**Rationale:** Files in the package are version controlled with code, easy to inspect and edit, and the inline version comment keeps version tracking close to the content.

---

### B8. Missing Prompt Templates

**Decision:** Create stub files now with correct filenames and version headers. Fill actual prompt content per-milestone when testable against real models.

**Rationale:** Stubs establish the naming convention and version tracking infrastructure immediately. Real prompt content requires iterative testing against model output, which is best done during each milestone.

---

## C. External Dependency Decisions

### C9. LadybugDB Integration

> **ANTI-CONFUSION WARNING:** The graph database used in this project is **LadybugDB** (package name `ladybug`, import `import ladybug as lb`). It was formerly known as Kuzu. Do NOT use `import kuzu` or `pip install kuzu`. The correct usage is:
>
> ```python
> import ladybug as lb
> db = lb.Database("artifacts/graph.ladybug")
> conn = lb.Connection(db)
> conn.execute("CREATE NODE TABLE ...")
> conn.execute("MATCH ... RETURN ...")
> ```
>
> API reference: https://docs.ladybugdb.com/client-apis/python

**Decision:**

- Use **LadybugDB** (formerly Kuzu) as the graph store.
- Python package: `uv add ladybug`. Import: `import ladybug as lb`.
- Embedded database: no server required.
- Uses Cypher query language for node/edge operations.
- Database file: `artifacts/graph.ladybug`.
- Python API: `lb.Database()`, `lb.Connection(db)`, `conn.execute(cypher)`.
- v0.15.3, MIT license, 991 stars on GitHub.

**Alternatives considered:**
- SQLite tables for graph data: loses graph-native queries and traversal efficiency.
- NetworkX + SQLite: adds complexity for minimal needs.
- Neo4j: requires Java, too heavy for local-first use.

**Rationale:** LadybugDB is embedded (no server), uses Cypher (expressive for graph queries), has Python bindings, and is purpose-built for this kind of relationship graph. It matches the local-first, single-user philosophy perfectly.

---

### C10. Chain/Graph Orchestration Framework Role

**Decision:** Drop third-party chain and graph orchestration frameworks from the core stack. Orchestration will use plain Python with a custom event bus.

**Rationale:** The orchestration needs are simple state machines (stage transitions, retries, resume). Plain Python with an event bus is simpler, fewer dependencies, more debuggable, and easier to reason about. The openai package handles LLM communication directly.

**Action required:** Keep SPEC.md section 5.3 limited to the chosen stack.

---

### C11. MLflow Setup

**Decision:**

- Use MLflow with **SQLite backend tracking** (not file-based, per issue mlflow/mlflow#18534).
- Tracking URI: `sqlite:///artifacts/mlflow.db`.
- Operator views dashboards via: `mlflow ui --backend-store-uri sqlite:///artifacts/mlflow.db`.

**Rationale:** SQLite backend is the modern recommended approach for MLflow local tracking. The database file sits alongside other project artifacts for easy cleanup.

---

## D. Pipeline Gap Decisions

### D12. Idiom Milestone Placement

**Decision:** Move the idiom workflow to M5 position, immediately after summaries (M4) and before packets.

**Rationale:** The spec places idioms in Phase 0 preprocessing. M8 (packets) depends on the idiom contract being available. Placing idioms before graph enrichment and packets keeps the dependency chain clean: M1 → M3 → M4 → M5 idioms → M6/M7 graph → M8 packets.

---

### D13. Revised Milestone Order

**Decision:** Reorder milestones to build the full graph before packets, and move idioms earlier. This results in 14 milestones (previously 14, now with different ordering):

| Milestone | Description | Task Brief |
|-----------|-------------|------------|
| M1 | EPUB Round-Trip | task-01 |
| M2 | Single-Chapter Translation | task-02 |
| M3 | Canonical Glossary | task-03 |
| M4 | Summary Memory | task-04 |
| M5 | Idiom Workflow | task-05 |
| M6 | Graph MVP | task-06 |
| M7 | Lightweight World Model | task-07 |
| M8 | Chapter Packets (with graph) | task-08 |
| M9 | Pass 3 + Risk Handling | task-09 |
| M10 | Orchestration + Production | task-10 |
| M11 | Cleanup Workflow | task-11 |
| M12 | CLI + TUI | task-12 |
| M13 | Observability + Evaluation | task-13 |
| M14 | Batch Pilot | task-14 |

Key changes from original:
- Idioms moved to M5 and now use `task-05-idioms.md`.
- Graph MVP (M6) and World Model (M7) now come before Packets (M8).
- Packet Integration is merged into M8 since graph data is available from the start.
- Total remains 14 milestones but ordering reflects actual dependency chain.

**Rationale:** Building the full graph (MVP + World Model) before packets allows packets to incorporate graph data from the start, eliminating the separate "Packet Integration" milestone. This is simpler and avoids retrofitting.

---

### D14. Resegmentation Logic

**Decision:** Trigger resegmentation only when Pass 1 output fails structural validation (placeholders missing, block mapping broken). Split the failed block at sentence boundaries and retry each segment independently.

Resegmentation flow:

1. Split the **original source block** `B` into segments at sentence boundaries.
2. **Pass 1 retries each segment independently** using segment text only as source.
3. Segments are processed sequentially. **Pass 2 for segment `S_n` receives: (a) the original full source block `B` as context, (b) the translations of all prior segments `[T_1, ..., T_{n-1}]` for cross-segment coherence, and (c) the current segment draft `S_n` as the correction target.** Prior translations prevent tense, tone, and naming drift between segments.
4. After all segments pass, concatenate segment outputs in order to reconstruct the final block output.
5. If any segment fails after retry, the entire block is marked failed.

**Rationale:** Reactive resegmentation on structural failure is the minimum viable approach and aligns with the spec's "retry once with stricter settings" failure handling. Providing the full original block as Pass 2 context prevents the correction model from losing narrative context, while keeping the correction scope narrow to a single segment. Supplying prior segment translations prevents "Frankenstein" paragraphs where segments diverge in tone, tense, or naming.

---

### D15. Summary Format

**Decision:**

- `chapter_summary_zh_structured`: JSON object with typed fields:

```json
{
  "chapter_number": 3,
  "characters_mentioned": ["张三", "李四"],
  "key_events": ["张三加入青云门", "李四获得秘籍"],
  "new_terms": ["青云门", "玄天秘籍"],
  "relationships_changed": [
    {"entity": "张三", "change": "became disciple of 青云门"}
  ],
  "setting": "青云山",
  "tone": "tense",
  "narrative_progression": "张三踏上修仙之路，遭遇初次考验"
}
```

- `chapter_summary_zh_short`: just the `narrative_progression` field (concise prose summary).

**Materialization mandate:**

The `generate_chapter_summary()` function in M4 extracts `narrative_progression` from the structured LLM response and writes **two** rows in a single SQLite transaction:

1. `summary_type = 'chapter_summary_zh_structured'`, `content_zh = <full JSON string>`
2. `summary_type = 'chapter_summary_zh_short'`, `content_zh = <narrative_progression string>`

This is not a separate pipeline stage. The `summary_repo.save()` method receives the structured JSON response and writes both rows atomically; it does not store raw JSON for lazy splitting. Downstream consumers (packet assembly, translation) perform zero JSON parsing to obtain the short summary — they read the dedicated `chapter_summary_zh_short` row directly.

**Rationale:** JSON structured summaries are machine-parseable, easy to validate, and directly usable in packet assembly. The short summary serves the continuity chain without needing to parse the full structure. Single-transaction materialization eliminates the risk of a downstream agent implementing lazy parsing.

---

### D16. Context Injection (Bundle to Prompt)

**Decision:** Prompt templates use **Python `str.format()`** named-section replacement. Section names are uppercase identifiers in curly braces (e.g., `{GLOSSARY}`, `{CONTEXT}`). The render function is `render_named_sections(template: str, sections: dict[str, str]) -> str` and raises `KeyError` if any referenced section is missing from the input dict. No conditionals, loops, nested expressions, or template engine beyond `str.format()`.

Example template:

```
# version: 1.0

## GLOSSARY
{GLOSSARY}

## CONTEXT
{CONTEXT}

## SOURCE TEXT
{SOURCE_TEXT}

## INSTRUCTIONS
Translate the source text into English...
```

**Alternatives considered:**
- Jinja2 (`{{ GLOSSARY }}`): adds a dependency for simple key-value substitution.
- Custom delimiter (e.g., `⟦GLOSSARY⟧`): would collide with the placeholder namespace.
- f-string: requires variables in scope at definition site, not suitable for file-loaded templates.

**Rationale:** `str.format()` is stdlib, sufficient for flat named-section replacement, and consistent with the `{section}` syntax already shown in examples. It avoids adding Jinja2 or a custom parser while keeping templates debuggable and version-controllable.

---

### D21. Paragraph Risk Score Formula

**Decision:** Use a weighted sum of six deterministic sub-scores clamped to [0.0, 1.0]. The threshold is configurable (default 0.7). All sub-score values are persisted for auditing.

Formula:

```
risk = min(1.0,
    idiom_density * 0.20
  + title_density * 0.15
  + relationship_reveal * 0.20
  + pronoun_ambiguity * 0.20
  + xhtml_fragility * 0.15
  + entity_density * 0.10
)
```

Each sub-score saturates at 1.0 based on count thresholds (e.g., 3+ idioms, 2+ ambiguous pronouns, 5+ placeholders).

**Alternatives considered:**
- LLM-based risk assessment: non-deterministic, non-auditable.
- Single-threshold heuristic on character count: too coarse.
- No formula documented: every agent invents its own risk math, making metrics incomparable.

**Rationale:** A deterministic formula makes risk scores reproducible across runs and agents, supports meaningful observability comparisons, and keeps the skip-Pass-3 decision auditable.

---

### D22. Tokenization Strategy

**Decision:** Use `tiktoken` (Cl100k encoding) for all token counting in packet building, budget enforcement, and context size estimation. `tiktoken` is already a transitive dependency via the `openai` package. The utility function `llm.tokens.count_tokens(text: str) -> int` wraps this and is introduced in M2 alongside the LLM client.

**Rules:**

- Packet assembly (M8) calls `count_tokens()` on each assembled section to verify total does not exceed `max_context_per_pass`.
- **Safety buffer: before comparing to any budget, multiply the raw tiktoken count by 1.05.** This compensates for the 2-3% undercount on Qwen-family models. The effective budget for packet assembly is `floor(max_context_per_pass / 1.05)` = 46811 raw tiktoken tokens (using default `max_context_per_pass` of 49152).
- Do not use character-ratio heuristics or generic tokenizers.
- Do not require a running inference server for pre-computation token counting.
- `tiktoken` Cl100k is within 2-3% accuracy for Qwen-family models, which is sufficient for budget enforcement when the 5% safety buffer is applied.

**Alternatives considered:**

- llama.cpp `/tokenize` endpoint: exact match but requires a running server and adds latency to offline pre-computation.
- Character-ratio heuristic (e.g., `len(text) / 4`): too inaccurate for budget enforcement across Chinese and English text with mixed tokenization behavior.
- No tokenizer specified: every agent invents its own counting method, making budgets incomparable across runs.
- No safety buffer: a 3% undercount on a 49152-token packet yields ~50626 actual tokens, still within the 65k window but eating into headroom for response tokens and system prompt overhead.

**Rationale:** `tiktoken` is fast, offline, deterministic, already available as a transitive dependency, and accurate enough for budget enforcement. The 5% safety buffer converts the 2-3% accuracy margin from a risk into a non-issue. Budgets are set at 75% of the context window (49152 of 65536), and the buffer reduces the effective ceiling to ~46811 raw tokens — still well within the window with comfortable headroom.

---

### D23. Entity Extraction Fallback Behavior

**Decision:** When the entity extractor (M6) encounters a term in a glossary-covered category (character, faction, location, technique, item_artifact, realm_concept, creature_race, event) with no matching locked glossary entry:

1. Do **not** create a LadybugDB graph entity. This prevents dual-truth scenarios where graph entity names diverge from glossary names.
2. Write a `deferred_entity` record to SQLite with fields: `deferred_id`, `term_text`, `category`, `evidence_snippet`, `source_chapter`, `discovered_at`, `status = 'pending_glossary'`, `glossary_entry_id = null`.
3. Emit a `warning_emitted` event with message noting the deferred term and chapter.
4. The `deferred_entity` table is visible to M3 (glossary discovery) as candidate input — the glossary discovery worker may consider deferred entities alongside its own extraction candidates.
5. Re-running M6 after glossary promotion resolves pending deferred entries: for each `deferred_entity` with status `pending_glossary`, check if a locked glossary entry now exists for the term. If so, update status to `promoted` and create the graph entity with the new `glossary_entry_id`.
6. Status lifecycle: `pending_glossary` → `promoted` (glossary entry created) → `graph_created` (graph entity created).

**Alternatives considered:**

- Create provisional LadybugDB entity with null `glossary_entry_id`: creates dual-truth risk; graph and glossary can diverge on naming.
- Silently skip with no record: the term is lost and will never feed back into glossary discovery.
- Halt M6 and require M3 first: over-rigid for an iterative workflow where glossary grows incrementally.

**Rationale:** Deferred entities in SQLite preserve extraction discoveries without polluting the graph with unverified names. The SQLite table serves as a bridge between graph extraction and glossary discovery, enabling iterative refinement. The status lifecycle makes progress visible and auditable.

---

## E. Operational Polish Decisions

### E17. Logging Configuration

**Decision:** Use loguru with dual-format output.
- Console: colored, human-readable.
- File: JSON structured logs at `artifacts/logs/` for MLflow/TUI parsing.
- Rotation: 10MB per file, keep 5 files.

**Rationale:** loguru is listed in the spec stack. Dual format serves both the operator (console) and observability (structured JSON). Rotation settings are conservative for local-first operation.

---

### E18. Resource Budget Concrete Values

**Decision:** Accept the defaults from config:
- `max_context_per_pass`: 49152 (~75% of 65536 context window) — this is the **absolute ceiling**; enforcement applies the 5% safety buffer from D22 before comparing, yielding an effective raw-token limit of ~46811.
- `max_paragraph_chars`: 2000
- `max_bundle_bytes`: 4096
- Degrade order: broad_continuity → fuzzy_candidates → rerank_depth → pass3 → fallback_model
- Pass 3 auto-disabled if bundle exceeds 75% of context budget.

**Rationale:** These are sensible starting defaults for a 65K context window on consumer hardware. The safety buffer is applied automatically at enforcement time; the operator configures the absolute ceiling in `max_context_per_pass`.

---

### E19. Embedding System

**Decision:** Design the embedding interface now (`llm/embeddings.py` stub), implement later at M7+ when packets and graph exist.

**Rationale:** The spec only needs embeddings for "fuzzy alias and epithet support" (retrieval tier 6). Exact matching (tiers 1-3) handles the critical path. Designing the interface now prevents architecture surprises; implementation can wait until lower-priority tiers are needed.

---

### E20. Golden Set Schema

**Decision:** JSON test files stored in `tests/golden_set/` with source_zh, expected_en, category tags, and difficulty markers.

Example structure:

```json
{
  "id": "idiom_001",
  "category": "idiom",
  "difficulty": "high",
  "source_zh": "他一箭双雕...",
  "expected_en": "He killed two birds with one stone...",
  "tags": ["idiom", "four-character-idiom"]
}
```

**Rationale:** JSON files are version-controllable, easy to review, and simple to load in tests. No DB overhead for static test data.

---

## Decision Log Summary

| ID | Decision | Chosen Option | Key Rationale |
|----|----------|---------------|---------------|
| A1 | Config schema | TOML + dataclasses + incremental fill | Stdlib, simple, versionable |
| A2 | Block definition | Leaf XHTML element, 1500-char max, sentence split | Natural translation unit, prevents overflow |
| A3 | Placeholder system | `⟦TYPE_N⟧` Unicode brackets, explicit type codes | Visually distinct, model-friendly |
| A4 | SQLite foundation | `artifacts/resemantica.db`, WAL mode mandatory, manual migrations | WAL prevents TUI lock errors, simple, inspectable |
| A5 | Test strategy | pytest, mirrored layout, fixture EPUB + mocks | Standard, reliable, fast |
| B6 | LLM client | openai package, llama.cpp router mode, rich client | Standard, router handles model switching |
| B7 | Prompt management | Files in llm/prompts/, inline version comments | Version-controlled, inspectable |
| B8 | Prompt templates | Stubs now, fill per-milestone | Establishes convention, defers untestable content |
| C9 | Graph store | LadybugDB (`import ladybug as lb`), embedded, Cypher | Graph-native, embedded, local-first |
| C10 | Chain/graph orchestration frameworks | Dropped from stack | Simple state machines suffice |
| C11 | MLflow | SQLite backend tracking at artifacts/mlflow.db | Modern recommended approach |
| D12 | Idiom placement | M5 (after summaries, before packets) | Matches spec Phase 0, satisfies M5 dependency |
| D13 | Milestone reorder | 14 milestones, graph before packets | Eliminates retrofitting, cleaner dependency chain |
| D14 | Resegmentation | Structural failure only; sequential Pass 2 with prior segment translations for coherence | Minimum viable, reactive, prevents cross-segment drift |
| D15 | Summary format | JSON structured + short prose | Machine-parseable, packet-friendly |
| D16 | Context injection | `str.format()` named sections, no template engine | Stdlib, debuggable, consistent syntax |
| D21 | Risk score formula | Weighted sum of 6 sub-scores, clamped [0,1], threshold 0.7 | Deterministic, auditable, comparable across runs |
| D22 | Tokenization | tiktoken Cl100k, offline, via `llm.tokens.count_tokens()`, 5% safety buffer | Transitive dep, deterministic, buffer covers 2-3% Qwen margin |
| D23 | Entity fallback | Deferred entity SQLite table, no LadybugDB node until glossary promotion | Prevents dual-truth, bridges extraction to glossary discovery |
| E17 | Logging | loguru, dual-format, 10MB rotation | Spec stack, serves both console and observability |
| E18 | Budget values | 49152/2000/4096 defaults from config | Sensible for 65K context |
| E19 | Embeddings | Interface stub now, implement at M7+ | Lower priority, design ahead |
| E20 | Golden set | JSON files in tests/golden_set/ | Version-controllable, simple |

---

## Document Alignment Status

These decisions have been applied to the existing project documents:

1. **SPEC.md** — section 5.3 stays limited to the chosen stack, and milestone section 26 matches the revised ordering.
2. **ARCHITECT.md** — build order matches the revised milestones.
3. **DATA_CONTRACT.md** — contracts remain format-neutral and now have a clean ending.
4. **IMPLEMENTATION_PLAN.md** — milestone order reflects idiom placement and packet integration merge.
5. **docs/10-architecture/module-boundaries.md** — includes `llm/prompts/` and `db/migrations/`.
6. **docs/10-architecture/storage-topology.md** — includes `artifacts/graph.ladybug` and `artifacts/mlflow.db`.
7. **docs/30-operations/repo-map.md** — notes that `src/resemantica/` does not yet exist.
8. **Task briefs** — task numbering now follows milestone order; retired packet integration is no longer a claimable task.
9. **docs/20-lld/** — LLD numbering now follows milestone order; retired packet integration is no longer a claimable LLD.
