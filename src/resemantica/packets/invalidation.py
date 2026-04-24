from __future__ import annotations

from resemantica.packets.models import PacketMetadataRecord, PacketStaleness


def detect_stale_packet(
    packet_metadata: PacketMetadataRecord | None,
    *,
    chapter_source_hash: str,
    glossary_version_hash: str,
    summary_version_hash: str,
    graph_snapshot_hash: str,
    idiom_policy_hash: str,
) -> PacketStaleness:
    if packet_metadata is None:
        return PacketStaleness(
            is_stale=True,
            reasons=["missing_packet_metadata"],
        )

    reasons: list[str] = []
    if packet_metadata.chapter_source_hash != chapter_source_hash:
        reasons.append("chapter_source_hash_changed")
    if packet_metadata.glossary_version_hash != glossary_version_hash:
        reasons.append("glossary_version_hash_changed")
    if packet_metadata.summary_version_hash != summary_version_hash:
        reasons.append("summary_version_hash_changed")
    if packet_metadata.graph_snapshot_hash != graph_snapshot_hash:
        reasons.append("graph_snapshot_hash_changed")
    if packet_metadata.idiom_policy_hash != idiom_policy_hash:
        reasons.append("idiom_policy_hash_changed")

    return PacketStaleness(
        is_stale=bool(reasons),
        reasons=reasons,
    )

