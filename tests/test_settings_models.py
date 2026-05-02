from __future__ import annotations

import pytest

from resemantica.settings import AppConfig, load_config


def _config_with_custom_models(**kwargs) -> AppConfig:
    config = AppConfig()
    for key, value in kwargs.items():
        setattr(config.models, key, value)
    return config


class TestEffectiveMaxContextPerPass:
    def test_uses_global_fallback_when_no_per_model_fields(self) -> None:
        config = AppConfig()
        result = config.models.effective_max_context_per_pass(
            "translator", config.budget.max_context_per_pass, config.llm.context_window
        )
        assert result == config.budget.max_context_per_pass

    def test_uses_global_fallback_for_analyst(self) -> None:
        config = AppConfig()
        result = config.models.effective_max_context_per_pass(
            "analyst", config.budget.max_context_per_pass, config.llm.context_window
        )
        assert result == config.budget.max_context_per_pass

    def test_uses_per_model_window_with_default_ratio(self) -> None:
        config = _config_with_custom_models(analyst_context_window=240000)
        result = config.models.effective_max_context_per_pass(
            "analyst", 49152, 65536
        )
        assert result == 180000

    def test_uses_per_model_window_and_custom_ratio(self) -> None:
        config = _config_with_custom_models(
            analyst_context_window=240000,
            analyst_max_context_ratio=0.5,
        )
        result = config.models.effective_max_context_per_pass(
            "analyst", 49152, 65536
        )
        assert result == 120000

    def test_per_model_window_is_trusted_even_when_below_global_budget(self) -> None:
        config = _config_with_custom_models(translator_context_window=1000)
        result = config.models.effective_max_context_per_pass(
            "translator", 49152, 65536
        )
        assert result == 750

    def test_translator_override(self) -> None:
        config = _config_with_custom_models(
            translator_context_window=65000,
            translator_max_context_ratio=0.75,
        )
        result = config.models.effective_max_context_per_pass(
            "translator", 49152, 65536
        )
        assert result == 48750

    def test_raises_on_unknown_role(self) -> None:
        config = AppConfig()
        with pytest.raises(ValueError, match="Unknown model role"):
            config.models.effective_max_context_per_pass("embedding", 49152, 65536)


class TestEffectiveContextWindow:
    def test_global_fallback(self) -> None:
        config = AppConfig()
        result = config.models.effective_context_window("translator", 65536)
        assert result == 65536

    def test_per_model_override(self) -> None:
        config = _config_with_custom_models(analyst_context_window=240000)
        result = config.models.effective_context_window("analyst", 65536)
        assert result == 240000

    def test_raises_on_unknown_role(self) -> None:
        config = AppConfig()
        with pytest.raises(ValueError, match="Unknown model role"):
            config.models.effective_context_window("embedding", 65536)


class TestValidateConfig:
    def test_accepts_valid_per_model_values(self, tmp_path) -> None:
        toml_content = """
[models]
translator_name = "model-t"
translator_context_window = 65000
translator_max_context_ratio = 0.75
analyst_name = "model-a"
analyst_context_window = 240000
analyst_max_context_ratio = 0.8
embedding_name = "bge"

[llm]
base_url = "http://localhost:8080"

[budget]
max_context_per_pass = 49152

[paths]
artifact_root = "artifacts"
db_filename = "test.db"
"""
        config_path = tmp_path / "resemantica.toml"
        config_path.write_text(toml_content)
        config = load_config(config_path)
        assert config.models.translator_context_window == 65000
        assert config.models.translator_max_context_ratio == 0.75
        assert config.models.analyst_context_window == 240000
        assert config.models.analyst_max_context_ratio == 0.8

    def test_accepts_missing_per_model_fields(self, tmp_path) -> None:
        toml_content = """
[models]
translator_name = "model-t"
analyst_name = "model-a"
embedding_name = "bge"

[paths]
artifact_root = "artifacts"
db_filename = "test.db"
"""
        config_path = tmp_path / "resemantica.toml"
        config_path.write_text(toml_content)
        config = load_config(config_path)
        assert config.models.translator_context_window is None
        assert config.models.analyst_context_window is None
        assert config.models.translator_max_context_ratio is None
        assert config.models.analyst_max_context_ratio is None

    def test_default_toml_parsing_matches_dataclass_defaults(self, tmp_path) -> None:
        toml_content = """
[llm]
base_url = "http://localhost:8080"
context_window = 65000

[models]
translator_name = "t"
analyst_name = "a"
embedding_name = "e"

[budget]
max_context_per_pass = 49152
max_paragraph_chars = 2000
max_bundle_bytes = 4096

[paths]
artifact_root = "artifacts"
db_filename = "test.db"
"""
        config_path = tmp_path / "resemantica.toml"
        config_path.write_text(toml_content)
        config = load_config(config_path)
        assert config.models.translator_context_window is None
        assert config.models.analyst_context_window is None
        eff_translator = config.models.effective_max_context_per_pass(
            "translator", config.budget.max_context_per_pass, config.llm.context_window
        )
        assert eff_translator == config.budget.max_context_per_pass
