from __future__ import annotations

import re
from datetime import UTC, datetime
from hashlib import sha256

from resemantica.glossary.models import GlossaryCandidate, GlossaryConflict, LockedGlossaryEntry

_GLOSSARY_CATEGORIES: set[str] = {
    "character", "alias", "title_honorific", "faction", "location",
    "technique", "item_artifact", "realm_concept", "creature_race",
    "generic_role", "event", "idiom",
}

_PLACEHOLDER_RE = re.compile(r"⟦/?[A-Z]+_\d+⟧")
_WHITESPACE_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ASCII_ALPHA_RE = re.compile(r"[A-Za-z]")


def normalize_term(term: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", term.strip())
    return normalized.casefold()


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
    return f"gconf_{digest}"


def _entry_id(
    *,
    release_id: str,
    category: str,
    normalized_source_term: str,
    normalized_target_term: str,
) -> str:
    digest = sha256(
        f"{release_id}:{category}:{normalized_source_term}:{normalized_target_term}".encode("utf-8")
    ).hexdigest()[:24]
    return f"glex_{digest}"


def _classify_conflict(reason: str) -> str:
    if reason.startswith("duplicate_target"):
        return "duplicate_target"
    if reason.startswith("naming_policy"):
        return "naming_policy"
    if reason.startswith("category"):
        return "category_policy"
    return "canon_conflict"


def validate_candidates_for_promotion(
    *,
    candidates: list[GlossaryCandidate],
    existing_entries: list[LockedGlossaryEntry],
    approval_run_id: str,
) -> tuple[list[LockedGlossaryEntry], list[GlossaryConflict]]:
    existing_by_source = {
        (entry.category, entry.normalized_source_term): entry for entry in existing_entries
    }
    existing_by_target = {
        (entry.category, entry.normalized_target_term): entry for entry in existing_entries
    }

    duplicate_target_map: dict[tuple[str, str], set[str]] = {}
    for candidate in candidates:
        target = normalize_term(candidate.candidate_translation_en or "")
        if not target:
            continue
        duplicate_target_map.setdefault((candidate.category, target), set()).add(
            candidate.normalized_source_term
        )

    approved_at = datetime.now(UTC).isoformat()
    promotion_entries: list[LockedGlossaryEntry] = []
    conflicts: list[GlossaryConflict] = []

    for candidate in candidates:
        reasons: list[tuple[str, str | None]] = []
        target_term = (candidate.candidate_translation_en or "").strip()
        normalized_target = normalize_term(target_term)

        if candidate.category not in _GLOSSARY_CATEGORIES:
            reasons.append((f"category_invalid: {candidate.category}", None))
        if not candidate.normalized_source_term.strip():
            reasons.append(("naming_policy: empty normalized source term", None))
        if not target_term:
            reasons.append(("naming_policy: empty candidate translation", None))
        if _PLACEHOLDER_RE.search(target_term):
            reasons.append(("naming_policy: target contains placeholder token", None))
        if _CJK_RE.search(target_term):
            reasons.append(("naming_policy: target contains CJK characters", None))
        if target_term and not _ASCII_ALPHA_RE.search(target_term):
            reasons.append(("naming_policy: target must include ASCII alphabetic characters", None))

        duplicate_key = (candidate.category, normalized_target)
        duplicate_sources = duplicate_target_map.get(duplicate_key, set())
        if normalized_target and len(duplicate_sources) > 1:
            reasons.append(
                (
                    f"duplicate_target: {target_term!r} maps from multiple source terms in category {candidate.category}",
                    None,
                )
            )

        canon_source = existing_by_source.get((candidate.category, candidate.normalized_source_term))
        if canon_source is not None and normalize_term(canon_source.target_term) != normalized_target:
            reasons.append(
                (
                    f"canon_conflict: source term already approved as {canon_source.target_term!r}",
                    canon_source.glossary_entry_id,
                )
            )

        canon_target = existing_by_target.get((candidate.category, normalized_target))
        if canon_target is not None and canon_target.normalized_source_term != candidate.normalized_source_term:
            reasons.append(
                (
                    f"canon_conflict: target term already assigned to source {canon_target.source_term!r}",
                    canon_target.glossary_entry_id,
                )
            )

        if reasons:
            for reason, existing_glossary_id in reasons:
                conflict_type = _classify_conflict(reason)
                conflicts.append(
                    GlossaryConflict(
                        conflict_id=_conflict_id(
                            release_id=candidate.release_id,
                            candidate_id=candidate.candidate_id,
                            conflict_type=conflict_type,
                            conflict_reason=reason,
                        ),
                        release_id=candidate.release_id,
                        candidate_id=candidate.candidate_id,
                        conflict_type=conflict_type,
                        conflict_reason=reason,
                        existing_glossary_id=existing_glossary_id,
                        schema_version=1,
                    )
                )
            continue

        promotion_entries.append(
            LockedGlossaryEntry(
                glossary_entry_id=_entry_id(
                    release_id=candidate.release_id,
                    category=candidate.category,
                    normalized_source_term=candidate.normalized_source_term,
                    normalized_target_term=normalized_target,
                ),
                release_id=candidate.release_id,
                source_term=candidate.source_term,
                normalized_source_term=candidate.normalized_source_term,
                target_term=target_term,
                normalized_target_term=normalized_target,
                category=candidate.category,
                status="approved",
                approved_at=approved_at,
                approval_run_id=approval_run_id,
                source_candidate_id=candidate.candidate_id,
                schema_version=1,
            )
        )

    return promotion_entries, conflicts

