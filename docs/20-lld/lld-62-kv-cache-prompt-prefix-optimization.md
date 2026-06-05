# LLD 62: KV-Cache Prompt Prefix Optimization

## Summary

Eight selected non-HY-MT prompts now put stable instructions, constraints, and output schemas before volatile per-call inputs. This maximizes the identical prompt prefix seen by local inference backends that reuse KV cache across calls.

No prompt rendering, parser, cache storage, LLM client, or provider API behavior changes are introduced. The change is limited to prompt text layout and prompt version bumps.

## Affected Prompts

| Prompt | Version | Dynamic input moved after stable prefix |
|--------|---------|------------------------------------------|
| `glossary_translate_gemma.txt` | 2.1 -> 2.2 | `{CATEGORY}`, `{EVIDENCE_SNIPPET}`, `{SOURCE_TERM}` |
| `glossary_evaluate.txt` | 1.2 -> 1.3 | `{CANDIDATES_JSON}` |
| `idiom_evaluate.txt` | 1.2 -> 1.3 | `{CANDIDATES_JSON}` |
| `idiom_detect.txt` | 2.0 -> 2.1 | `{CHAPTER_NUMBER}`, `{SOURCE_TEXT_ZH}` |
| `idiom_meaning.txt` | 2.1 -> 2.2 | `{MEANING_ZH}` |
| `graph_extract.txt` | 2.2 -> 2.3 | `{CHAPTER_NUMBER}`, `{SOURCE_TEXT_ZH}`, `{GLOSSARY_CONTEXT}` |
| `translate_pass2.txt` | 2.4 -> 2.5 | `{GLOSSARY}`, `{ALIAS_RESOLUTIONS}`, `{MATCHED_IDIOMS}`, `{LOCAL_RELATIONSHIPS}`, `{CONTINUITY_NOTES}`, `{RETRIEVAL_EVIDENCE}`, `{SOURCE_TEXT}`, `{DRAFT_TEXT}`, `{FULL_SOURCE_BLOCK}`, `{PRIOR_SEGMENTS}` |
| `translate_pass3.txt` | 1.2 -> 1.3 | `{SOURCE_TEXT}`, `{PASS2_OUTPUT}`, `{GLOSSARY}`, `{ALIAS_RESOLUTIONS}`, `{MATCHED_IDIOMS}`, `{RELATIONSHIP_CONSTRAINTS}` |

## Prompt Layout Contract

The intended layout is:

1. Stable task name and behavior instructions.
2. Stable strict rules and output schema.
3. Dynamic input block containing all per-call values.

Existing section headers and labels are preserved where local tests and mock LLMs inspect rendered prompts, such as `## CHAPTER NUMBER`, `## SOURCE TEXT (ZH)`, `## CANDIDATES`, `## LOCKED GLOSSARY`, `Source:`, `Draft:`, and Pass 3 context section headers.

## HY-MT Boundary

The fragile translator-prompt constraint applies to HY-MT-specific prompt patterns, especially prompts whose wording and context-first layout were tuned for HY-MT behavior. The eight prompts in this slice are not HY-MT prompt files. They may be prefix-optimized as long as their output contracts and parser-visible section names remain compatible.

HY-MT prompt files remain untouched.

## Cache Behavior

Each edited prompt bumps its inline `# version: ...` header. Existing caches, checkpoints, graph extraction drafts, glossary votes, idiom artifacts, and translation pass artifacts keyed by prompt version become stale through the current versioning mechanism. No manual cache migration is needed.

## Validation

- `tests/llm/test_analyst_prompt_policy.py` checks that schema and anti-restart constraints remain visible.
- The same policy tests assert that volatile placeholders appear after stable rules or schemas.
- Glossary, idiom, graph, and translation test suites cover parser compatibility for rendered prompts.

## Out Of Scope

- HY-MT prompt rewrites.
- Prompt rendering or named-section API changes.
- LLM client request shape changes.
- Provider-side KV-cache configuration.
