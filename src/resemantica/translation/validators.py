from __future__ import annotations

from dataclasses import dataclass, field
import re

_PLACEHOLDER_RE = re.compile(r"⟦/?[A-Z]+_\d+⟧")


@dataclass(slots=True)
class ValidationResult:
    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.status == "success"


def _placeholder_tokens(text: str) -> list[str]:
    return _PLACEHOLDER_RE.findall(text)


def validate_structure(source_text: str, candidate_text: str) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not candidate_text.strip():
        errors.append("Candidate output is empty.")

    source_placeholders = _placeholder_tokens(source_text)
    candidate_placeholders = _placeholder_tokens(candidate_text)
    if source_placeholders != candidate_placeholders:
        errors.append(
            "Placeholder mismatch between source and candidate output."
        )

    if not source_placeholders and candidate_placeholders:
        warnings.append("Candidate introduced placeholders where source had none.")

    return ValidationResult(status="failed" if errors else "success", errors=errors, warnings=warnings)


def validate_basic_fidelity(source_text: str, output_text: str) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not output_text.strip():
        errors.append("Translated output is empty.")
    if output_text.strip() == source_text.strip():
        warnings.append("Output is identical to source text.")

    return ValidationResult(status="failed" if errors else "success", errors=errors, warnings=warnings)

