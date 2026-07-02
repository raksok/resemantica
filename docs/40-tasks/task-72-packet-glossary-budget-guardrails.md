# Task 72: Packet Glossary Budget Guardrails

## Goal

Prevent `packets-build` failures caused by `chapter_glossary_subset` exceeding
the translator packet budget.

## Implementation

- Add deterministic, budgeted glossary subset selection in the packet builder.
- Prioritize specific and translation-critical glossary matches before short
  generic matches.
- Keep the full locked glossary hash for packet staleness.
- Add glossary trimming as the last packet-budget degradation step.
- Bump the packet builder version so existing packet artifacts rebuild.

## Validation

- Unit-test glossary prioritization and trimming.
- Add a synthetic glossary-heavy packet build that stays under budget.
- Keep existing packet graph, bundle, staleness, and translation budget tests
  passing.

## Notes

No new config is introduced. The glossary cap is derived from the packet budget
already passed into packet build.
