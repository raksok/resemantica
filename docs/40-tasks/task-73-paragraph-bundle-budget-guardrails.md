# Task 73: Paragraph Bundle Budget Guardrails

## Goal

Prevent `bundle_skip` warnings caused by paragraph bundle context exceeding
`[packets].max_bundle_bytes`.

## Implementation

- Compact matched glossary, idiom, alias, and relationship rows before bundle
  sizing.
- Extend bundle degradation to trim matched idioms and glossary entries after
  lower-priority graph and continuity sections.
- Keep the existing bundle schema fields so translation formatters remain
  compatible.
- Bump the packet builder version so existing packet and bundle artifacts
  rebuild.

## Validation

- Unit-test glossary-heavy and idiom-heavy bundle trimming.
- Add a packet build regression test that writes bundles without `bundle_skip`
  warnings under glossary-heavy pressure.
- Keep packet and translation bundle context tests passing.

## Notes

No new config is introduced. `[packets].max_bundle_bytes` remains the paragraph
bundle byte cap.
