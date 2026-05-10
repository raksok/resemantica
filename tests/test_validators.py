from __future__ import annotations

import pytest

from resemantica.validators import ValidationResult


def test_validation_result_default_is_success() -> None:
    result = ValidationResult()

    assert result.status == "success"
    assert result.is_valid is True


def test_validation_result_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="ValidationResult.status"):
        ValidationResult(status="pass")  # type: ignore[arg-type]
