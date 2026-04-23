# Module Boundaries

## Target Package Layout

```text
src/resemantica/
  cli.py
  settings.py
  logging_config.py
  config/
  epub/
    extractor.py
    parser.py
    placeholders.py
    rebuild.py
    models.py
    validators.py
  llm/
    client.py
    prompts.py
    embeddings.py
    models.py
    prompts/
      translate_pass1.txt
      translate_pass2.txt
      translate_pass3.txt
      glossary_discover.txt
      glossary_translate.txt
      summary_zh_structured.txt
      summary_zh_short.txt
      summary_en_derive.txt
      summary_validate.txt
      idiom_detect.txt
      entity_extract.txt
      relationship_extract.txt
      translate_with_context.txt
      translate_with_term.txt
      translate_with_term_and_context.txt
  db/
    sqlite.py
    models.py
    run_repo.py
    checkpoint_repo.py
    migrations/
      001_initial.sql
  glossary/
    discovery.py
    translation.py
    normalization.py
    matching.py
    validators.py
    repo.py
  summaries/
    generator.py
    validators.py
    derivation.py
    repo.py
  idioms/
    extractor.py
    matching.py
    validators.py
    repo.py
  packets/
    builder.py
    bundler.py
    models.py
    invalidation.py
    repo.py
  graph/
    client.py
    models.py
    extractor.py
    validators.py
    filters.py
  translation/
    pass1.py
    pass2.py
    pass3.py
    validators.py
    checkpoints.py
  orchestration/
    events.py
    runner.py
    cleanup.py
    resume.py
  tracking/
    mlflow.py
    artifacts.py
  tui/
    app.py
    screens.py
    presenters.py
  utils/
    hashing.py
    paths.py
    time.py
```

## Ownership Rules

- `settings.py` owns config loading and path derivation inputs.
- `epub/` owns EPUB unpack, chapter/block extraction, placeholder mapping, and rebuild validation.
- `llm/` owns model invocation abstractions and prompt metadata, not stage-specific workflow decisions.
- `db/` owns SQLite access, generic models, and operational (run/checkpoint) repositories.
- `glossary/`, `summaries/`, `idioms/`, `graph/`, `packets/`, and `translation/` own subsystem behavior, domain-specific repositories, and validators.
- `orchestration/` owns stage ordering, retries, resume logic, cleanup, and event emission.
- `tracking/` adapts orchestration events and artifacts to MLflow and artifact stores.
- `tui/` renders operator state only.

## Public Interfaces

Expected top-level interfaces:

- `uv run python -m resemantica.cli epub-roundtrip`
- `uv run python -m resemantica.cli translate-chapter`
- `uv run python -m resemantica.cli translate-range`
- `uv run python -m resemantica.cli preprocess glossary-discover`
- `uv run python -m resemantica.cli preprocess summaries`
- `uv run python -m resemantica.cli preprocess idioms`
- `uv run python -m resemantica.cli packets build`
- `uv run python -m resemantica.cli run production`
- `uv run python -m resemantica.cli rebuild-epub`
- `uv run python -m resemantica.cli tui`

The LLDs define the exact command behavior and required arguments for each stage.

## Import Rules

- `tui/` may import orchestration event models and presenters, but not lower-level repositories directly.
- `translation/` may import `packets.models`, `llm.client`, and specific repository interfaces for readonly lookups.
- `db/` must not import `translation/` or `tui/`.
- Common value objects should live in the owning subsystem or `db/models.py` only when shared by several repositories.
