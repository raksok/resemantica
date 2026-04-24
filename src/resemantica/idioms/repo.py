from __future__ import annotations

import sqlite3
from typing import Sequence

from resemantica.db.idiom_repo import (
    ensure_idiom_schema,
    find_exact_policy,
    insert_conflicts,
    insert_detected_candidates,
    list_candidates,
    list_candidates_for_promotion,
    list_conflicts,
    list_policies,
    mark_candidate_approved,
    mark_candidate_conflict,
    promote_policies,
)
from resemantica.idioms.models import IdiomCandidate, IdiomConflict, IdiomPolicy


class IdiomRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ensure_schema(self) -> None:
        ensure_idiom_schema(self.conn)

    def insert_candidates(self, *, candidates: Sequence[IdiomCandidate]) -> None:
        insert_detected_candidates(self.conn, candidates=candidates)

    def list_candidates(self, *, release_id: str) -> list[IdiomCandidate]:
        return list_candidates(self.conn, release_id=release_id)

    def list_candidates_for_promotion(self, *, release_id: str) -> list[IdiomCandidate]:
        return list_candidates_for_promotion(self.conn, release_id=release_id)

    def mark_candidate_conflict(self, *, candidate_id: str, conflict_reason: str) -> None:
        mark_candidate_conflict(self.conn, candidate_id=candidate_id, conflict_reason=conflict_reason)

    def mark_candidate_approved(self, *, candidate_id: str) -> None:
        mark_candidate_approved(self.conn, candidate_id=candidate_id)

    def insert_conflicts(self, *, conflicts: Sequence[IdiomConflict]) -> None:
        insert_conflicts(self.conn, conflicts=conflicts)

    def list_conflicts(self, *, release_id: str) -> list[IdiomConflict]:
        return list_conflicts(self.conn, release_id=release_id)

    def promote_policies(self, *, policies: Sequence[IdiomPolicy]) -> None:
        promote_policies(self.conn, policies=policies)

    def list_policies(self, *, release_id: str) -> list[IdiomPolicy]:
        return list_policies(self.conn, release_id=release_id)

    def find_exact_policy(
        self,
        *,
        release_id: str,
        normalized_source_text: str,
    ) -> IdiomPolicy | None:
        return find_exact_policy(
            self.conn,
            release_id=release_id,
            normalized_source_text=normalized_source_text,
        )

