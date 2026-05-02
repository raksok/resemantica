from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class IdiomCandidate:
    candidate_id: str
    release_id: str
    source_text: str
    normalized_source_text: str
    meaning_zh: str
    preferred_rendering_en: str
    usage_notes: str | None
    first_seen_chapter: int
    last_seen_chapter: int
    appearance_count: int
    evidence_snippet: str
    detection_run_id: str
    candidate_status: str
    validation_status: str
    conflict_reason: str | None
    analyst_model_name: str
    analyst_prompt_version: str
    meaning_en: str = ""
    translation_run_id: str | None = None
    translator_model_name: str | None = None
    translator_prompt_version: str | None = None
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class IdiomPolicy:
    idiom_id: str
    release_id: str
    source_text: str
    normalized_source_text: str
    meaning_zh: str
    preferred_rendering_en: str
    usage_notes: str | None
    policy_status: str
    first_seen_chapter: int
    last_seen_chapter: int
    appearance_count: int
    promoted_from_candidate_id: str
    approval_run_id: str
    meaning_en: str = ""
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class IdiomConflict:
    conflict_id: str
    release_id: str
    candidate_id: str
    conflict_type: str
    conflict_reason: str
    existing_idiom_id: str | None
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)

