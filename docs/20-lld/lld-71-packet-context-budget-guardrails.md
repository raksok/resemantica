# LLD 71: Packet Context Budget Guardrails

## Summary

Packet build remains deterministic assembly, but packet graph context is now
bounded before artifact write and translation passes perform a final prompt
budget check before model calls. The goal is to prevent long-release context
growth from surfacing as late LLM failures.

## Packet Budgeting

`packets.builder.enrich_with_graph_context()` still starts from chapter-safe
confirmed graph state. It selects chapter-local entities, direct alias hits,
glossary-linked entities, current-chapter appearances, local relationships,
relationship snippets, and reveal-safe notes in deterministic priority order.
The selected graph sections stop at an internal token budget before they are
stored in the packet.

`_apply_packet_budget()` counts every prompt-relevant packet section with the
existing 5% safety buffer. The effective packet budget is
`packets.budget_tokens` when configured, otherwise
`budget.max_context_per_pass`. Lower-priority packet sections still trim by the
existing degrade order.

Paragraph bundles use `packets.max_bundle_bytes`. Bundle trimming remains
lower-priority first: relationships, aliases, continuity notes, and retrieval
evidence.

## Translation Backstop

Pass 1, Pass 2, and Pass 3 render their prompt and call
`ensure_prompt_within_budget()` before `LLMClient.generate_text()`. Oversized
translation context fails with `prompt_budget_exceeded` and does not call the
model. Packet build is still responsible for trimming; translation does not
silently drop context at the final call site.

## Cache Impact

`PACKET_BUILDER_VERSION` is bumped and packet staleness checks compare stored
metadata against the current builder version. Existing packets built with older
budget semantics are rebuilt on the next packet stage run.

## Tests

- Packet budget accounting includes all prompt-relevant fields.
- Packet-specific budget and bundle-byte settings are honored.
- Large graph state is bounded while retaining local rows first.
- Builder-version mismatch marks packet metadata stale.
- Translation Pass 1, Pass 2, and Pass 3 fail before LLM calls when prompts
  exceed budget.
