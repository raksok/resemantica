from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ValidationStatus = Literal["success", "failed"]


@dataclass(slots=True)
class ValidationResult:
    status: ValidationStatus = "success"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in ("success", "failed"):
            raise ValueError("ValidationResult.status must be 'success' or 'failed'")

    @property
    def is_valid(self) -> bool:
        return self.status == "success"

    @property
    def combined_errors(self) -> list[str]:
        return self.errors + self.warnings
