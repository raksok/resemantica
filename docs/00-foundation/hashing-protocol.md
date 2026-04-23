# Hashing Protocol

## Purpose

To ensure deterministic cache invalidation and artifact reproducibility, all hashes must follow a strict serialization and generation protocol.

## Protocol

1.  **Algorithm**: SHA-256
2.  **Encoding**: Hexadecimal lowercase string.
3.  **JSON Serialization (Canonical JSON)**:
    - Keys must be sorted alphabetically.
    - No insignificant whitespace (no indentation, no spaces after separators).
    - UTF-8 encoding.
    - Example in Python: `json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')`

## Core Hashes

-   `chapter_source_hash`: Hash of the deterministic JSON representation of the extracted chapter blocks.
-   `glossary_version_hash`: Hash of the canonical JSON array of all active `locked_glossary` entries, sorted by `glossary_entry_id`.
-   `summary_version_hash`: Hash of the canonical JSON array of all `validated_summaries_zh` for the project, sorted by `chapter_number` and `summary_type`.
-   `graph_snapshot_hash`: Hash of the deterministic export of the confirmed LadybugDB graph state.
-   `idiom_policy_hash`: Hash of the canonical JSON array of all active `idiom_policies`, sorted by `idiom_id`.
