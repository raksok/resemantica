# LLD 66: Graph Chapter-Local Glossary Context

## Summary

Graph extraction now renders the locked glossary prompt context from only graph-relevant locked entries whose `source_term` appears literally in the current chapter source text.

The full graph-relevant locked glossary remains loaded in Python for deterministic post-LLM matching. This reduces prompt size without changing graph schemas, node shape, LadybugDB tables, or storage behavior.

## Behavior

For each graph extraction chapter:

1. Load the chapter source text.
2. Filter locked glossary entries to graph entity categories.
3. Render `GLOSSARY_CONTEXT` from entries where `entry.source_term in source_text`.
4. Use that same chapter-local context for static prompt budget calculation and every chunk prompt for the chapter.
5. Render `(none)` when no graph-relevant locked glossary source term appears in the chapter.

The exact locked glossary matching index is still built from all graph-relevant locked entries before chapter processing. Extracted entities that match a locked entry continue to use the locked target term and glossary entry ID.

## Freshness

Graph drafts remain keyed by release, run, chapter number, chapter source hash, and `graph_extract.txt` prompt version. The graph prompt version is `2.4`, so drafts generated with older graph prompts become stale once.

