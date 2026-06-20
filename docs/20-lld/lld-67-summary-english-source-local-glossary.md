# LLD 67: Summary English Source-Local Glossary

## Summary

English summary derivation now renders locked glossary context from only locked
entries whose `source_term` appears literally in the Chinese summary text being
translated.

This reduces `SUMMARY_EN_DERIVE` prompt size for both normal summary English
rows and graph-grounded continuity English rows. The full locked glossary still
drives provenance hashes, so storage invalidation remains conservative without a
schema change.

## Behavior

For each English summary derivation:

1. Receive the Chinese source summary text.
2. Filter locked glossary entries to entries where `entry.source_term in source_text_zh`.
3. Render `LOCKED_GLOSSARY` from that source-local list.
4. Render `(empty)` when no locked source term appears in the source summary.
5. Check the rendered prompt against the translator context budget before
   calling the LLM.

The relevance rule is exact substring matching only. Alias, fuzzy,
normalized-form, target-term, and simplified/traditional matching are not part
of this pass.

## Freshness

`summary_en_derive.txt` prompt version is `1.1`. New derivations and forced
reruns use source-local glossary context.

Rows in `derived_summaries_en` continue to store `glossary_version_hash` from
the full locked glossary. The prompt context is source-local, but the provenance
hash remains full-release glossary state.

