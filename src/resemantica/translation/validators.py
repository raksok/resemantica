from __future__ import annotations

import re

from resemantica.validators import ValidationResult

_PLACEHOLDER_RE = re.compile(r"⟦/?[A-Z]+_\d+⟧")


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


def validate_pass3_integrity(
    *,
    source_text: str,
    pass2_output: str,
    pass3_output: str,
    glossary_terms: list[str] | None = None,
) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not pass3_output.strip():
        errors.append("Pass 3 output is empty.")
        return ValidationResult(status="failed", errors=errors, warnings=warnings)

    source_placeholders = _placeholder_tokens(source_text)
    pass3_placeholders = _placeholder_tokens(pass3_output)
    if source_placeholders != pass3_placeholders:
        errors.append("Placeholder mismatch between source and Pass 3 output.")

    pass2_placeholders = _placeholder_tokens(pass2_output)
    if pass2_placeholders != pass3_placeholders:
        errors.append("Placeholder mismatch between Pass 2 and Pass 3 output.")

    terms = glossary_terms or []
    for term in terms:
        if term in pass2_output and term not in pass3_output:
            errors.append(f"Terminology drift: '{term}' lost in Pass 3.")

    if pass3_output.strip() == source_text.strip():
        warnings.append("Pass 3 output is identical to source text (meaning drift suspected).")

    return ValidationResult(status="failed" if errors else "success", errors=errors, warnings=warnings)

