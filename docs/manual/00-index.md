# Resemantica Manual

> Local-first EPUB translation pipeline for Chinese web novels

**Version:** 0.1.0  
**Entry point:** `rsem`  
**Python:** >= 3.13  
**License:** Proprietary

---

## Table of Contents

1. **[Introduction](01-introduction.md)** — What Resemantica is, key concepts, LLM roles, pipeline overview
2. **[Installation](02-installation.md)** — System requirements, setup, configuration
3. **[Quick Start](03-quick-start.md)** — End-to-end walkthrough from EPUB to translated output
4. **[Configuration](04-configuration.md)** — `resemantica.toml` reference: all sections, keys, defaults
5. **[Command Reference](05-command-reference.md)** — Complete reference for every command and subcommand
6. **[Pipeline Architecture](06-pipeline-architecture.md)** — Stage ordering, orchestration flows, gates, locks
7. **[Storage & Artifacts](07-storage-artifacts.md)** — SQLite schema, LadybugDB schema, filesystem layout
8. **[Exit Codes & Signals](08-exit-codes.md)** — Return codes and interrupt handling
9. **[Examples](09-examples.md)** — Common workflows and usage patterns
10. **[Troubleshooting](10-troubleshooting.md)** — Common issues, log locations, recovery
11. **[Cleanup Pipeline](11-cleanup-pipeline.md)** — Two-phase cleanup, scopes, safety
12. **[Human Review Workflow](12-human-review.md)** — Glossary and idiom review process

---

## Quick Links

| Resource | Location |
|----------|----------|
| Man page | `docs/rsem.1.md` |
| Architecture | `docs/10-architecture/` |
| Low-level design | `docs/20-lld/` |
| Task briefs | `docs/40-tasks/` |
| Specification | `SPEC.md` |
| Data contracts | `DATA_CONTRACT.md` |
| Design decisions | `DECISIONS.md` |
| Implementation plan | `IMPLEMENTATION_PLAN.md` |
