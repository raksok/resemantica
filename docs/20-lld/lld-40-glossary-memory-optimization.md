# LLD 40: Glossary Memory Optimization — Incremental Accumulation

## Summary

The M39 deterministic glossary pipeline accumulates every chapter's raw candidates in `per_chapter_raw: dict[int, list[RawCandidate]]` before merging and scoring. For 1000+ chapters this holds ~300K `RawCandidate` objects (~240 MB) for the entire loop duration, then creates a second copy during flatten/merge before the dict is freed. This LLD replaces that batch-at-end pattern with incremental accumulation: merge candidates and aggregate corpus statistics per-chapter in a single loop, eliminating the per-chapter dict entirely.

## Current State

```
for ref in chapter_refs:
    raw_candidates = generate_chapter_candidates(text)
    per_chapter_raw[chapter_number] = raw_candidates   # ← accumulate ALL chapters

stats = compute_corpus_stats(per_chapter_raw)            # ← reads dict, produces counts

all_raw_list = []                                         # ← flatten
for raw_list in per_chapter_raw.values():
    all_raw_list.extend(raw_list)
global_raw = merge_candidates(all_raw_list)               # ← deduplicate

scored_list = score_candidates(global_raw, stats)
candidates = [GlossaryCandidate(...) for sc in scored_list]
```

Problem:
- `per_chapter_raw` holds all chapters until the loop finishes
- Per-chapter `RawCandidate` objects survive the full loop duration
- `all_raw_list` duplicates references to the same objects
- GC cannot reclaim per-chapter objects until `per_chapter_raw` goes out of scope

## Target State

```
merged_accumulator: dict[str, RawCandidate] = {}
term_freq: dict[str, int] = {}
doc_freq: dict[str, int] = {}
total_chapters = 0

for ref in chapter_refs:
    raw_candidates = generate_chapter_candidates(text)

    merge_across_chapters(merged_accumulator, raw_candidates)  # ← incremental
    for rc in raw_candidates:                                   # ← per-chapter stats
        term_freq[rc.normalized_form] += rc.appearances
    for norm in {rc.normalized_form for rc in raw_candidates}:
        doc_freq[norm] += 1
    total_chapters += 1
    # raw_candidates goes out of scope → GC reclaims

stats = CorpusStats(term_freq, doc_freq, total_chapters, ...)
global_raw = list(merged_accumulator.values())
scored_list = score_candidates(global_raw, stats)
candidates = [GlossaryCandidate(...) for sc in scored_list]
```

## New Function

### `candidate_gen.py: merge_across_chapters()`

```python
def merge_across_chapters(
    accumulator: dict[str, RawCandidate],
    chapter_candidates: list[RawCandidate],
) -> dict[str, RawCandidate]:
    """
    Incremental merge: update accumulator with candidates from one chapter.
    Same merge logic as merge_candidates() but operates on a persistent dict
    owned by the caller. Call once per chapter.

    Returns the accumulator dict for convenience (caller already has the ref).
    """
```

Logic is identical to `merge_candidates()` (appearances sum, strategies union, snippet dedup, type_prior priority, NER label fill) but takes a pre-existing dict and mutates it rather than creating a new one.

## Modified Function

### `discovery.py: discover_candidates_from_extracted()`

Removed variables:
- `per_chapter_raw: dict[int, list[RawCandidate]]` — eliminated
- `all_raw_list: list[RawCandidate]` — eliminated

New variables:
- `merged_accumulator: dict[str, RawCandidate]` — single accumulation dict

Kept:
- `first_seen` / `last_seen` tracking (unchanged)
- Event callbacks (unchanged)
- `score_candidates()` call (unchanged)
- `GlossaryCandidate` construction (unchanged)
- Return type (unchanged)

Changed import:
- Remove: `compute_corpus_stats` (no longer called)
- Remove: `merge_candidates` (no longer called)
- Add: `merge_across_chapters` from `candidate_gen`
- Add: `CorpusStats` from `corpus_stats`

## Data Flow (Detailed)

```
Before (batch):
  per_chapter_raw dict [300K objects]
       │
       ├──→ compute_corpus_stats() → term_freq, doc_freq
       │
       └──→ flatten → merge_candidates() → scored → GlossaryCandidate

After (incremental):
  loop iteration:
    generate_chapter_candidates(text) → raw [~300 objects]
       ├──→ merge_across_chapters(accumulator, raw)     ← mutates single dict
       ├──→ accumulate term_freq, doc_freq, total_chapters  ← local counters
       └──→ [raw goes out of scope, GC reclaims]

  post-loop:
    list(accumulator.values()) → global_raw → score_candidates() → GlossaryCandidate
```

## Memory Profile (1000 chapters)

| Structure | Before | After |
|-----------|--------|-------|
| `per_chapter_raw` | 300K objects (~240 MB) | **0** |
| `all_raw_list` / flatten | 300K refs (~2 MB) | **0** |
| `merged_accumulator` | n/a (created during merge) | 50-100K objects (~80 MB) |
| `global_raw` (list of merged) | 50-100K refs (~1 MB) | **same** |
| `candidates` | 50-100K objects (~200 MB) | **same** |
| Per-chapter candidates lifetime | Held for full loop | Freed per iteration |
| **Peak** | **~440 MB** | **~280 MB** |

## Test Coverage

New test in `tests/glossary/test_candidate_gen.py`:

- `test_merge_across_chapters`: create candidates across 3 "chapters", call `merge_across_chapters()` incrementally, verify output matches `merge_candidates()` over flattened list
- Edge cases: empty list, single candidate, type_prior conflicts, NER label filling, snippet dedup

## Backward Compatibility

- `discover_candidates_from_extracted()`: same signature, same output
- `GlossaryCandidate` objects: same fields, same values
- `compute_corpus_stats()`: still exists in `corpus_stats.py` (tests depend on it), just no longer called from discovery
- `merge_candidates()`: still exists in `candidate_gen.py` (used by `generate_chapter_candidates()`), just no longer called from discovery
- No schema, config, or CLI changes

## Out Of Scope

- Parallelizing HanLP segmentation (future optimization)
- SQLite intermediate storage (not needed — incremental accumulation is sufficient)
- Non-story chapter filtering in glossary (already decided: minimal pollution, let pipeline handle it)
