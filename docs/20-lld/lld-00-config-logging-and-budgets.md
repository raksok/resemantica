# LLD 00: Config, Logging, and Budgets

## Summary

Define the shared runtime foundation for configuration loading, logging setup, and resource budget defaults before milestone-specific code depends on them.

## Public Interfaces

Config file:

- `resemantica.toml` in the project root

Python modules:

- `settings.load_config()`
- `settings.validate_config()`
- `logging_config.configure_logging()`

Config sections:

- `models`
- `llm`
- `paths`
- `budget`
- `translation`

## Data Flow

1. Read `resemantica.toml` from the project root.
2. Parse TOML with the Python standard library.
3. Hydrate plain dataclasses for config sections.
4. Run manual validation for required fields, value ranges, and path shape.
5. Derive default artifact paths, including `artifacts/` and `artifacts/resemantica.db`.
6. Configure loguru console logs and JSON file logs under `artifacts/logs/` (implemented in Task 19a, see LLD 19a).
7. Expose budget defaults to LLM, packet, and translation callers.

## Validation Ownership

- `settings.validate_config()` owns config schema validation.
- Missing or malformed config values produce a readable startup error.
- Budget validation rejects non-positive numeric limits.
- Logging setup creates repo-local log paths and must not write outside `artifacts/`.

## Resume And Rerun

- Runtime-affecting config values must be captured in run metadata through a config hash or version.
- A config hash change invalidates downstream artifacts that record the prior config version.
- Logging is append-oriented per run and must not overwrite previous run logs.

## Tests

- default config parsing from a minimal `resemantica.toml`
- validation failure for missing model names or invalid budget limits
- derived path defaults for `artifact_root` and `db_filename`
- loguru configuration writes JSON logs under `artifacts/logs/`

## Default Values

The initial defaults come from `DECISIONS.md`:

- `max_context_per_pass`: `49152`
- `max_paragraph_chars`: `2000`
- `max_bundle_bytes`: `4096`
- degrade order: `broad_continuity`, `fuzzy_candidates`, `rerank_depth`, `pass3`, `fallback_model`
- Pass 3 default: enabled
- high risk threshold: `0.7`

Risk score formula (see `lld-09-pass3-and-risk.md` for full detail):

```
risk = min(1.0,
    idiom_density_score * 0.20
  + title_density_score * 0.15
  + relationship_reveal_score * 0.20
  + pronoun_ambiguity_score * 0.20
  + xhtml_fragility_score * 0.15
  + entity_density_score * 0.10
)
```
