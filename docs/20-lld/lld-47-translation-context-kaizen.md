# LLD 47: Translation Context Kaizen

## Summary

Standardize how paragraph bundle context is formatted for translation Pass 1, Pass 2, Pass 3, and risk classification. Missing packet metadata or missing bundle files must degrade to empty context and warnings; they must not skip a chapter.

## Context Flow

`translation.bundle_context` owns bundle-to-prompt formatting:

- `format_bundle_for_pass1()` keeps the existing Pass 1 keys: glossary, alias resolutions, matched idioms, and continuity notes. Idioms now include `meaning_en`, `meaning_zh`, and `usage_notes` when available.
- `format_bundle_for_pass2()` emits labeled non-empty sections for terminology, aliases, idioms, local relationships, continuity, and retrieval evidence.
- `format_bundle_for_pass3()` emits preservation constraints for terminology, aliases, idiom renderings, and relationship facts.
- `extract_glossary_target_terms_for_pass3()` returns glossary target terms for Pass 3 integrity validation.

Empty or missing bundles return empty strings for every section. Pass prompts may contain placeholders for richer context, but empty context does not invent section labels.

Rendered Pass 1, Pass 2, and Pass 3 prompts are checked against the configured
prompt budget before each model call. Missing context still degrades to empty
strings, but oversized context fails clearly with `prompt_budget_exceeded`
instead of being trimmed at translation time.

## Pipeline Behavior

Pass 1 translates every extracted record. When a matching paragraph bundle is unavailable, it calls Pass 1 with empty context.

Pass 2 uses the richer Pass 2 formatter for normal blocks and resegmented block segments. Successful Pass 1 blocks are not skipped because packet or bundle context is missing.

Pass 3 uses the Pass 3 formatter and validates that glossary target terms present in Pass 2 output remain present after polishing. `force=True` bypasses Pass 3 cache reuse, matching Pass 1 and Pass 2 behavior.

Packet metadata lookup is best effort for translation checkpoint hashing. If the metadata table or row is absent, translation continues with `packet_version_hash = ""`; the bundle loader also warns and returns no context.

## Risk Classification

When bundles are available, risk still uses bundle counts for idioms, title/honorific glossary entries, entities, and reveal-gated relationships. Pronoun ambiguity is always computed from Pass 2 English output, because the translated text is where ambiguous English pronouns appear.

Relationship reveal risk is true only when relationship data marks masked or reveal-gated content, such as `is_masked_identity`, explicit reveal-gated flags, or a later `revealed_chapter`. Ordinary local relationships do not trigger reveal risk.

When no bundle exists, risk falls back to text-only heuristics.

## Cache Implications

Prompt version bumps invalidate old Pass 1, Pass 2, and Pass 3 checkpoints. Existing `packet_version_hash` checkpoint matching continues to invalidate cached translations when packet inputs change.

## Non-Skip Invariant

Translation context is advisory. Missing packet metadata, missing bundle files, missing bundle entries, and empty bundle sections must not skip a chapter or a successful block. Existing intentional skips remain unchanged: failed Pass 1 blocks are not processed by Pass 2, and high-risk Pass 3 blocks keep validated Pass 2 output.
