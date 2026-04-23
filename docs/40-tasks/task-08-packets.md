# Task 08: Chapter Packets with Graph Integration

- **Milestone:** M8
- **Depends on:** M3, M4, M5, M7

## Goal

Implement immutable chapter packet artifacts with graph context enrichment and narrow paragraph bundle derivation.

## Scope

In:

- packet schemas
- packet builder with graph context
- chapter-safe relationship snippets and alias resolution
- stale packet detection

Out:

- heavy live retrieval
- Pass 3

## Owned Files Or Modules

- `src/resemantica/packets/`
- `src/resemantica/db/packet_repo.py`
- `tests/packets/`

## Interfaces To Satisfy

- LLD: `../20-lld/lld-08-packets.md`
- artifact rules: `../30-operations/artifact-paths.md`

## Tests Or Smoke Checks

- packet schema test
- provenance hash presence
- stale packet detection
- graph-to-packet filtering
- packet size control
- retrieval precedence (glossary wins over graph)

## Done Criteria

- packets are immutable artifacts with metadata rows
- bundles remain narrow and chapter-safe
- stale upstream state forces rebuild behavior
- graph context is chapter-safe and size-controlled
