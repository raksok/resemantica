from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

GlossaryCategory = Literal[
    "character",
    "alias",
    "title_honorific",
    "faction",
    "location",
    "technique",
    "item_artifact",
    "realm_concept",
    "creature_race",
    "generic_role",
    "event",
    "idiom",
]

CandidateStatus = Literal["discovered", "filtered", "pruned", "translated", "conflict", "promoted"]
ValidationStatus = Literal["pending", "approved", "conflict"]
LockedGlossaryStatus = Literal["approved"]


@dataclass(slots=True)
class GlossaryCandidate:
    candidate_id: str
    release_id: str
    source_term: str
    normalized_source_term: str
    category: str
    source_language: str
    first_seen_chapter: int
    last_seen_chapter: int
    appearance_count: int
    evidence_snippet: str
    candidate_translation_en: str | None
    normalized_target_term: str | None
    discovery_run_id: str
    translation_run_id: str | None
    candidate_status: str
    validation_status: str
    conflict_reason: str | None
    critic_score: float | None = None
    analyst_model_name: str | None = None
    analyst_prompt_version: str | None = None
    translator_model_name: str | None = None
    translator_prompt_version: str | None = None
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class LockedGlossaryEntry:
    glossary_entry_id: str
    release_id: str
    source_term: str
    normalized_source_term: str
    target_term: str
    normalized_target_term: str
    category: str
    status: str
    approved_at: str
    approval_run_id: str
    source_candidate_id: str
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class GlossaryConflict:
    conflict_id: str
    release_id: str
    candidate_id: str
    conflict_type: str
    conflict_reason: str
    existing_glossary_id: str | None
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)

