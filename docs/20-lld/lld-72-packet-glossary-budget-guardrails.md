# LLD 72: Packet Glossary Budget Guardrails

## Summary

Packet build bounds the chapter glossary slice before packet artifact write.
This prevents glossary-heavy chapters from exceeding the translator packet
budget while keeping deterministic, high-value glossary authority context.

## Glossary Selection

The packet builder still loads the full locked glossary and hashes the full
locked glossary for packet staleness. The stored `chapter_glossary_subset`,
however, is selected from chapter source matches in priority order:

- translation-critical categories first, such as characters, factions,
  locations, artifacts, techniques, and realm concepts
- longer source terms before shorter terms within the same category
- repeated and earlier source occurrences as deterministic tie-breakers

The selected glossary JSON is capped to an internal budget derived from the
effective packet budget. This uses the same packet budget passed by
orchestration for the translator context limit.

## Packet Budget Fallback

`_apply_packet_budget()` still trims the existing lower-priority sections by
the configured degrade order first. If the packet remains oversized, it trims
low-priority glossary entries from the tail of `chapter_glossary_subset` until
the packet fits. `trimmed_sections` records `glossary_subset` once.

`packet_budget_exceeded` is reserved for cases where mandatory non-glossary
packet sections still exceed the effective packet budget.

## Cache Impact

`PACKET_BUILDER_VERSION` is bumped so packets built before glossary bounding
are stale and rebuild under the new budget semantics.

## Tests

- Glossary subset selection keeps specific terms before common short terms.
- Oversized glossary slices trim without repeated trim markers.
- Synthetic glossary-heavy chapters build under a translator-sized packet
  budget.
- Builder-version mismatch still marks packet metadata stale.
