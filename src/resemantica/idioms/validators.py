from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

from resemantica.idioms.models import IdiomCandidate, IdiomConflict, IdiomPolicy

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(slots=True)
class IdiomValidationResult:
    promotion_entries: list[IdiomPolicy]
    conflicts: list[IdiomConflict]
    promoted_candidate_ids: list[str]
    conflicted_candidate_ids: list[str]


def normalize_idiom_source(source_text: str) -> str:
    return _WHITESPACE_RE.sub(" ", source_text.strip()).casefold()


def normalize_rendering(rendering: str) -> str:
    return _WHITESPACE_RE.sub(" ", rendering.strip()).casefold()


def _normalize_free_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip())


def _policy_id(*, release_id: str, normalized_source_text: str) -> str:
    digest = sha256(f"{release_id}:{normalized_source_text}".encode("utf-8")).hexdigest()[:24]
    return f"idi_{digest}"


def _conflict_id(
    *,
    release_id: str,
    candidate_id: str,
    conflict_type: str,
    conflict_reason: str,
) -> str:
    digest = sha256(
        f"{release_id}:{candidate_id}:{conflict_type}:{conflict_reason}".encode("utf-8")
    ).hexdigest()[:24]
    return f"icf_{digest}"


def validate_idiom_policy(
    *,
    candidates: list[IdiomCandidate],
    existing_policies: list[IdiomPolicy],
    approval_run_id: str,
) -> IdiomValidationResult:
    existing_by_source = {
        policy.normalized_source_text: policy for policy in existing_policies
    }
    grouped: dict[str, list[IdiomCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.normalized_source_text, []).append(candidate)

    promotion_entries: list[IdiomPolicy] = []
    conflicts: list[IdiomConflict] = []
    promoted_candidate_ids: list[str] = []
    conflicted_candidate_ids: list[str] = []

    for normalized_source in sorted(grouped.keys()):
        group = sorted(
            grouped[normalized_source],
            key=lambda item: (item.first_seen_chapter, item.candidate_id),
        )
        lead = group[0]

        distinct_meanings = {
            _normalize_free_text(candidate.meaning_zh)
            for candidate in group
            if _normalize_free_text(candidate.meaning_zh)
        }
        distinct_renderings = {
            normalize_rendering(candidate.preferred_rendering_en)
            for candidate in group
            if normalize_rendering(candidate.preferred_rendering_en)
        }
        if len(distinct_meanings) > 1 or len(distinct_renderings) > 1:
            for candidate in group:
                reason = (
                    "duplicate_conflict: normalized source text maps to multiple "
                    "meanings or preferred renderings"
                )
                conflicts.append(
                    IdiomConflict(
                        conflict_id=_conflict_id(
                            release_id=candidate.release_id,
                            candidate_id=candidate.candidate_id,
                            conflict_type="duplicate_conflict",
                            conflict_reason=reason,
                        ),
                        release_id=candidate.release_id,
                        candidate_id=candidate.candidate_id,
                        conflict_type="duplicate_conflict",
                        conflict_reason=reason,
                        existing_idiom_id=None,
                        schema_version=1,
                    )
                )
                conflicted_candidate_ids.append(candidate.candidate_id)
            continue

        merged_meaning = ""
        merged_rendering = ""
        merged_usage: str | None = None
        for candidate in group:
            if not merged_meaning and candidate.meaning_zh.strip():
                merged_meaning = candidate.meaning_zh.strip()
            if not merged_rendering and candidate.preferred_rendering_en.strip():
                merged_rendering = candidate.preferred_rendering_en.strip()
            if merged_usage is None and candidate.usage_notes and candidate.usage_notes.strip():
                merged_usage = candidate.usage_notes.strip()

        if not normalized_source:
            for candidate in group:
                reason = "naming_policy: empty normalized source text"
                conflicts.append(
                    IdiomConflict(
                        conflict_id=_conflict_id(
                            release_id=candidate.release_id,
                            candidate_id=candidate.candidate_id,
                            conflict_type="naming_policy",
                            conflict_reason=reason,
                        ),
                        release_id=candidate.release_id,
                        candidate_id=candidate.candidate_id,
                        conflict_type="naming_policy",
                        conflict_reason=reason,
                        existing_idiom_id=None,
                        schema_version=1,
                    )
                )
                conflicted_candidate_ids.append(candidate.candidate_id)
            continue

        if not merged_meaning or not merged_rendering:
            for candidate in group:
                reason = "naming_policy: missing meaning_zh or preferred_rendering_en"
                conflicts.append(
                    IdiomConflict(
                        conflict_id=_conflict_id(
                            release_id=candidate.release_id,
                            candidate_id=candidate.candidate_id,
                            conflict_type="naming_policy",
                            conflict_reason=reason,
                        ),
                        release_id=candidate.release_id,
                        candidate_id=candidate.candidate_id,
                        conflict_type="naming_policy",
                        conflict_reason=reason,
                        existing_idiom_id=None,
                        schema_version=1,
                    )
                )
                conflicted_candidate_ids.append(candidate.candidate_id)
            continue

        existing = existing_by_source.get(normalized_source)
        merged_meaning_norm = _normalize_free_text(merged_meaning)
        merged_rendering_norm = normalize_rendering(merged_rendering)

        if existing is not None:
            existing_meaning_norm = _normalize_free_text(existing.meaning_zh)
            existing_rendering_norm = normalize_rendering(existing.preferred_rendering_en)
            if (
                existing_meaning_norm != merged_meaning_norm
                or existing_rendering_norm != merged_rendering_norm
            ):
                for candidate in group:
                    reason = (
                        "canon_conflict: normalized source text already approved with "
                        "different meaning or preferred rendering"
                    )
                    conflicts.append(
                        IdiomConflict(
                            conflict_id=_conflict_id(
                                release_id=candidate.release_id,
                                candidate_id=candidate.candidate_id,
                                conflict_type="canon_conflict",
                                conflict_reason=reason,
                            ),
                            release_id=candidate.release_id,
                            candidate_id=candidate.candidate_id,
                            conflict_type="canon_conflict",
                            conflict_reason=reason,
                            existing_idiom_id=existing.idiom_id,
                            schema_version=1,
                        )
                    )
                    conflicted_candidate_ids.append(candidate.candidate_id)
                continue

        policy = IdiomPolicy(
            idiom_id=_policy_id(
                release_id=lead.release_id,
                normalized_source_text=normalized_source,
            ),
            release_id=lead.release_id,
            source_text=existing.source_text if existing is not None else lead.source_text,
            normalized_source_text=normalized_source,
            meaning_zh=existing.meaning_zh if existing is not None else merged_meaning,
            preferred_rendering_en=(
                existing.preferred_rendering_en if existing is not None else merged_rendering
            ),
            usage_notes=existing.usage_notes if existing is not None else merged_usage,
            policy_status="approved",
            first_seen_chapter=min(
                [candidate.first_seen_chapter for candidate in group]
                + ([existing.first_seen_chapter] if existing is not None else [])
            ),
            last_seen_chapter=max(
                [candidate.last_seen_chapter for candidate in group]
                + ([existing.last_seen_chapter] if existing is not None else [])
            ),
            appearance_count=sum(candidate.appearance_count for candidate in group)
            + (existing.appearance_count if existing is not None else 0),
            promoted_from_candidate_id=lead.candidate_id,
            approval_run_id=approval_run_id,
            schema_version=1,
        )
        promotion_entries.append(policy)
        promoted_candidate_ids.extend(candidate.candidate_id for candidate in group)

    return IdiomValidationResult(
        promotion_entries=promotion_entries,
        conflicts=conflicts,
        promoted_candidate_ids=sorted(set(promoted_candidate_ids)),
        conflicted_candidate_ids=sorted(set(conflicted_candidate_ids)),
    )

