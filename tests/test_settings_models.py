from __future__ import annotations

from pathlib import Path

import pytest

from resemantica.settings import AppConfig, derive_paths, load_config


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


class TestPreprocessTranslatorNames:
    def test_defaults_to_primary_translator(self) -> None:
        config = AppConfig()

        assert config.models.effective_preprocess_translator_names() == [
            config.models.translator_name
        ]

    def test_uses_configured_preprocess_translators(self) -> None:
        config = _config_with_custom_models(
            translator_name="fallback-translator",
            preprocess_translator_names=["model-a", "model-b", "model-c"],
        )

        assert config.models.effective_preprocess_translator_names() == [
            "model-a",
            "model-b",
            "model-c",
        ]

    def test_strips_empty_configured_preprocess_translators(self) -> None:
        config = _config_with_custom_models(
            translator_name="fallback-translator",
            preprocess_translator_names=["", "  ", "model-a"],
        )

        assert config.models.effective_preprocess_translator_names() == ["model-a"]


class TestEmbeddingModelConfig:
    def test_default_embedding_model_uses_canonical_huggingface_id(self) -> None:
        config = AppConfig()

        assert config.models.embedding_name == "BAAI/bge-m3"

    def test_checked_in_config_uses_canonical_huggingface_id(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "resemantica.toml"

        config = load_config(config_path)

        assert config.models.embedding_name == "BAAI/bge-m3"


class TestDerivedPaths:
    def test_release_stores_are_release_scoped(self, tmp_path: Path) -> None:
        config = AppConfig()

        p1 = derive_paths(config, release_id="p1", project_root=tmp_path)
        pf = derive_paths(config, release_id="pf", project_root=tmp_path)

        assert p1.db_path == tmp_path / "artifacts" / "releases" / "p1" / "resemantica.db"
        assert pf.db_path == tmp_path / "artifacts" / "releases" / "pf" / "resemantica.db"
        assert p1.graph_db_path == tmp_path / "artifacts" / "releases" / "p1" / "graph.ladybug"
        assert pf.graph_db_path == tmp_path / "artifacts" / "releases" / "pf" / "graph.ladybug"
        assert p1.db_path != pf.db_path
        assert p1.graph_db_path != pf.graph_db_path


class TestValidateConfig:
    def test_summary_config_defaults(self) -> None:
        config = AppConfig()

        assert config.summaries.chapter_concurrency == 1
        assert config.summaries.story_compact_max_tokens == 2048

    def test_accepts_summary_concurrency_and_compact_budget(self, tmp_path) -> None:
        toml_content = """
[models]
translator_name = "model-t"
analyst_name = "model-a"
embedding_name = "bge"

[summaries]
chapter_concurrency = 3
story_compact_max_tokens = 1024

[paths]
artifact_root = "artifacts"
db_filename = "test.db"
"""
        config_path = tmp_path / "resemantica.toml"
        config_path.write_text(toml_content)
        config = load_config(config_path)

        assert config.summaries.chapter_concurrency == 3
        assert config.summaries.story_compact_max_tokens == 1024

    @pytest.mark.parametrize("value", [0, 6])
    def test_rejects_invalid_summary_concurrency(self, tmp_path, value) -> None:
        toml_content = f"""
[models]
translator_name = "model-t"
analyst_name = "model-a"
embedding_name = "bge"

[summaries]
chapter_concurrency = {value}

[paths]
artifact_root = "artifacts"
db_filename = "test.db"
"""
        config_path = tmp_path / "resemantica.toml"
        config_path.write_text(toml_content)

        with pytest.raises(ValueError, match="summaries.chapter_concurrency"):
            load_config(config_path)

    def test_rejects_invalid_story_compact_budget(self, tmp_path) -> None:
        toml_content = """
[models]
translator_name = "model-t"
analyst_name = "model-a"
embedding_name = "bge"

[summaries]
story_compact_max_tokens = 0

[paths]
artifact_root = "artifacts"
db_filename = "test.db"
"""
        config_path = tmp_path / "resemantica.toml"
        config_path.write_text(toml_content)

        with pytest.raises(ValueError, match="summaries.story_compact_max_tokens"):
            load_config(config_path)

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

    def test_accepts_preprocess_translator_names(self, tmp_path) -> None:
        toml_content = """
[models]
translator_name = "model-t"
preprocess_translator_names = ["model-t", "model-u", "model-v"]
analyst_name = "model-a"
embedding_name = "bge"

[paths]
artifact_root = "artifacts"
db_filename = "test.db"
"""
        config_path = tmp_path / "resemantica.toml"
        config_path.write_text(toml_content)
        config = load_config(config_path)
        assert config.models.effective_preprocess_translator_names() == [
            "model-t",
            "model-u",
            "model-v",
        ]

    def test_checked_in_config_enables_multi_model_preprocess_translation(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "resemantica.toml"

        config = load_config(config_path)
        effective_names = config.models.effective_preprocess_translator_names()

        assert config.models.preprocess_translator_names
        assert config.models.translator_name in effective_names
        assert len(effective_names) >= 2

    def test_translation_batched_model_order_defaults_to_true(self, tmp_path) -> None:
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

        assert config.translation.batched_model_order is True

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

    def test_accepts_llm_per_model_concurrency(self, tmp_path) -> None:
        toml_content = """
[llm]
max_concurrent_requests_per_model = 3

[models]
translator_name = "t"
analyst_name = "a"
embedding_name = "e"

[paths]
artifact_root = "artifacts"
db_filename = "test.db"
"""
        config_path = tmp_path / "resemantica.toml"
        config_path.write_text(toml_content)
        config = load_config(config_path)

        assert config.llm.max_concurrent_requests_per_model == 3

    def test_rejects_invalid_llm_per_model_concurrency(self, tmp_path) -> None:
        toml_content = """
[llm]
max_concurrent_requests_per_model = 0

[models]
translator_name = "t"
analyst_name = "a"
embedding_name = "e"

[paths]
artifact_root = "artifacts"
db_filename = "test.db"
"""
        config_path = tmp_path / "resemantica.toml"
        config_path.write_text(toml_content)

        with pytest.raises(ValueError, match="llm.max_concurrent_requests_per_model"):
            load_config(config_path)
