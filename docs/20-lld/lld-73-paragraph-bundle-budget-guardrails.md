# LLD 73: Paragraph Bundle Budget Guardrails

## Summary

Paragraph bundles compact local context before artifact write and trim all
variable sections until the bundle fits `[packets].max_bundle_bytes`. Budget
pressure should produce smaller bundle rows, not missing bundle rows.

## Bundle Context Compaction

The bundle builder keeps the existing `ParagraphBundle` fields but stores only
formatter-needed keys in matched rows:

- glossary: ID, source term, target term, category
- idioms: ID, source text, preferred rendering, meaning, usage notes
- aliases: ID, alias text, entity ID, entity name
- relationships: ID, type, entity IDs, lore text, masked-identity flag

This avoids duplicating full packet rows into every paragraph bundle.

## Bundle Degradation

Bundle trimming remains deterministic. The builder first clears lower-priority
context sections: relationships, aliases, continuity notes, and retrieval
evidence. If the bundle still exceeds `[packets].max_bundle_bytes`, it trims
matched idioms and then matched glossary entries from the low-priority tail.

Glossary ordering preserves translation-critical categories, longer source
terms, repeated source hits, and earlier source occurrences first. Idiom
ordering preserves longer and earlier source matches first.

`bundle_budget_exceeded` is reserved for exceptional cases where the minimal
bundle skeleton cannot fit the configured byte cap.

## Cache Impact

`PACKET_BUILDER_VERSION` is bumped so packets and bundles built before bundle
context compaction are stale and rebuild under the new semantics.

## Tests

- Glossary-heavy paragraph bundles trim glossary matches and fit the byte cap.
- Idiom-heavy paragraph bundles trim idiom matches and fit the byte cap.
- Packet build writes bundle rows instead of `bundle_skip` warnings under
  glossary-heavy bundle pressure.
- Existing translation bundle formatters accept compact bundle rows.
