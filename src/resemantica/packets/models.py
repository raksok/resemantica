from __future__ import annotations

from dataclasses import asdict, dataclass, field


PACKET_SCHEMA_VERSION = 1
BUNDLE_SCHEMA_VERSION = 1
PACKET_BUILDER_VERSION = "m8.packet_builder.v1"


@dataclass(slots=True)
class ChapterPacket:
    packet_id: str
    release_id: str
    run_id: str
    chapter_number: int
    chapter_metadata: dict[str, object]
    chapter_glossary_subset: list[dict[str, object]]
    previous_3_summaries: list[dict[str, object]]
    story_so_far_summary: str
    chapter_summary_short: str
    active_arc_summary: str | None
    chapter_local_idioms: list[dict[str, object]]
    graph_snapshot_reference: dict[str, object]
    entity_context: list[dict[str, object]]
    relationship_context: list[dict[str, object]]
    chapter_safe_relationship_snippets: list[dict[str, object]]
    alias_resolution_candidates: list[dict[str, object]]
    reveal_safe_identity_notes: list[dict[str, object]]
    warnings: list[str]
    trimmed_sections: list[str]
    section_token_counts: dict[str, dict[str, int]]
    packet_schema_version: int
    chapter_source_hash: str
    glossary_version_hash: str
    summary_version_hash: str
    graph_snapshot_hash: str
    idiom_policy_hash: str
    packet_builder_version: str
    built_at: str

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ParagraphBundle:
    bundle_id: str
    release_id: str
    chapter_number: int
    block_id: str
    matched_glossary_entries: list[dict[str, object]]
    alias_resolutions: list[dict[str, object]]
    matched_idioms: list[dict[str, object]]
    local_relationships: list[dict[str, object]]
    continuity_notes: list[str]
    retrieval_evidence_summary: list[str]
    risk_classification: str
    packet_ref: str
    schema_version: int = BUNDLE_SCHEMA_VERSION
    buffered_token_count: int = 0
    size_bytes: int = 0
    trimmed_sections: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class PacketMetadataRecord:
    packet_id: str
    release_id: str
    chapter_number: int
    run_id: str
    packet_path: str
    bundle_path: str
    packet_hash: str
    chapter_source_hash: str
    glossary_version_hash: str
    summary_version_hash: str
    graph_snapshot_hash: str
    idiom_policy_hash: str
    packet_builder_version: str
    packet_schema_version: int = PACKET_SCHEMA_VERSION
    built_at: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class PacketStaleness:
    is_stale: bool
    reasons: list[str]


@dataclass(slots=True)
class PacketBuildOutput:
    status: str
    release_id: str
    run_id: str
    chapter_number: int
    packet_id: str
    packet_hash: str
    packet_path: str
    bundle_path: str
    stale_reasons: list[str]

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)

