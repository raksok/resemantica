from __future__ import annotations

from resemantica.idioms.models import IdiomPolicy


def match_idioms(*, text: str, idiom_policies: list[IdiomPolicy]) -> list[IdiomPolicy]:
    matches = [policy for policy in idiom_policies if policy.source_text in text]
    return sorted(
        matches,
        key=lambda policy: (-len(policy.source_text), policy.normalized_source_text),
    )

