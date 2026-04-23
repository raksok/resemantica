# System Overview

## Purpose

Resemantica is a local-first pipeline that translates long-form Chinese web novel EPUBs into readable English EPUBs while preserving structure, continuity, naming consistency, and auditability.

The system is intentionally staged. It is not a one-shot prompt chain and it is not a generic agent runtime.

## System Shape

The intended execution path is:

1. Deterministically ingest and validate a source EPUB.
2. Build offline memory assets and chapter packets.
3. Translate chapter-by-chapter with narrow packet-derived context.
4. Rebuild a valid translated EPUB.
5. Expose progress, artifacts, retries, and cleanup through shared orchestration.

## Current Repo State

Today the repository contains the specification set and a minimal Python entrypoint. The implementation package layout described in this docs suite is the target shape that future work should create under `src/resemantica/`.

## Intended Package Layout

```text
src/resemantica/
  cli.py
  settings.py
  logging_config.py
  config/
  epub/
  llm/
  db/
  glossary/
  summaries/
  idioms/
  packets/
  graph/
  translation/
  orchestration/
  tui/
  tracking/
  utils/
tests/
docs/
```

## Reading Paths

- New implementer: start with this file, then `decision-rules.md`, `module-boundaries.md`, and the relevant LLD.
- Task owner: read the task brief in `docs/40-tasks/` and its referenced LLD.
- Reviewer: read the LLD, then compare the code and tests against the acceptance criteria.
