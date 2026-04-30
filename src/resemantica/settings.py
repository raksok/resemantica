from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib


@dataclass(slots=True)
class ModelsConfig:
    translator_name: str = "HY-MT1.5-7B"
    analyst_name: str = "Qwen3.5-9B-GLM5.1"
    embedding_name: str = "bge-M3"


@dataclass(slots=True)
class LLMConfig:
    base_url: str = "http://localhost:8080"
    timeout_seconds: int = 300
    max_retries: int = 2
    context_window: int = 65536


@dataclass(slots=True)
class PathsConfig:
    artifact_root: str = "artifacts"
    db_filename: str = "resemantica.db"


@dataclass(slots=True)
class BudgetConfig:
    max_context_per_pass: int = 49152
    max_paragraph_chars: int = 2000
    max_bundle_bytes: int = 4096
    degrade_order: list[str] = field(
        default_factory=lambda: [
            "broad_continuity",
            "fuzzy_candidates",
            "rerank_depth",
            "pass3",
            "fallback_model",
        ]
    )


@dataclass(slots=True)
class TranslationConfig:
    pass3_default: bool = True
    risk_threshold_high: float = 0.7
    batched_model_order: bool = False


@dataclass(slots=True)
class SummariesConfig:
    exclude_chapter_patterns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EventsConfig:
    persistence_mode: str = "normal"
    progress_sample_every: int = 25


@dataclass(slots=True)
class AppConfig:
    models: ModelsConfig = field(default_factory=ModelsConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    summaries: SummariesConfig = field(default_factory=SummariesConfig)
    events: EventsConfig = field(default_factory=EventsConfig)


@dataclass(slots=True)
class DerivedPaths:
    project_root: Path
    artifact_root: Path
    release_root: Path
    unpacked_dir: Path
    extracted_chapters_dir: Path
    extracted_chapter_manifest_path: Path
    extracted_reports_dir: Path
    extracted_placeholders_dir: Path
    glossary_dir: Path
    glossary_candidates_path: Path
    glossary_conflicts_path: Path
    idioms_dir: Path
    idiom_candidates_path: Path
    idiom_policies_path: Path
    idiom_conflicts_path: Path
    summaries_dir: Path
    graph_dir: Path
    graph_snapshot_path: Path
    graph_warnings_path: Path
    graph_db_path: Path
    packets_dir: Path
    rebuilt_epub_path: Path
    db_path: Path


def _read_toml(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        return {}
    with config_path.open("rb") as handle:
        parsed = tomllib.load(handle)
    if not isinstance(parsed, dict):
        raise ValueError("Config root must be a TOML table.")
    return parsed


def _table(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Config section [{key}] must be a table.")
    return value


def _as_str(value: object, field_name: str) -> str:
    if isinstance(value, str):
        return value
    raise ValueError(f"{field_name} must be a string.")


def _as_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise ValueError(f"{field_name} must be an integer.")


def _as_float(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric.")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise ValueError(f"{field_name} must be numeric.")


def _as_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{field_name} must be a boolean.")


def _as_str_list(value: object, field_name: str) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise ValueError(f"{field_name} must be a list of strings.")


def load_config(config_path: Path | None = None) -> AppConfig:
    resolved_path = config_path or Path.cwd() / "resemantica.toml"
    raw = _read_toml(resolved_path)

    models = _table(raw, "models")
    llm = _table(raw, "llm")
    paths = _table(raw, "paths")
    budget = _table(raw, "budget")
    translation = _table(raw, "translation")
    summaries = _table(raw, "summaries")
    events = _table(raw, "events")

    config = AppConfig(
        models=ModelsConfig(
            translator_name=_as_str(
                models.get("translator_name", ModelsConfig().translator_name),
                "models.translator_name",
            ),
            analyst_name=_as_str(
                models.get("analyst_name", ModelsConfig().analyst_name),
                "models.analyst_name",
            ),
            embedding_name=_as_str(
                models.get("embedding_name", ModelsConfig().embedding_name),
                "models.embedding_name",
            ),
        ),
        llm=LLMConfig(
            base_url=_as_str(llm.get("base_url", LLMConfig().base_url), "llm.base_url"),
            timeout_seconds=_as_int(
                llm.get("timeout_seconds", LLMConfig().timeout_seconds),
                "llm.timeout_seconds",
            ),
            max_retries=_as_int(
                llm.get("max_retries", LLMConfig().max_retries),
                "llm.max_retries",
            ),
            context_window=_as_int(
                llm.get("context_window", LLMConfig().context_window),
                "llm.context_window",
            ),
        ),
        paths=PathsConfig(
            artifact_root=_as_str(
                paths.get("artifact_root", PathsConfig().artifact_root),
                "paths.artifact_root",
            ),
            db_filename=_as_str(
                paths.get("db_filename", PathsConfig().db_filename),
                "paths.db_filename",
            ),
        ),
        budget=BudgetConfig(
            max_context_per_pass=_as_int(
                budget.get("max_context_per_pass", BudgetConfig().max_context_per_pass),
                "budget.max_context_per_pass",
            ),
            max_paragraph_chars=_as_int(
                budget.get("max_paragraph_chars", BudgetConfig().max_paragraph_chars),
                "budget.max_paragraph_chars",
            ),
            max_bundle_bytes=_as_int(
                budget.get("max_bundle_bytes", BudgetConfig().max_bundle_bytes),
                "budget.max_bundle_bytes",
            ),
            degrade_order=_as_str_list(
                budget.get("degrade_order", BudgetConfig().degrade_order),
                "budget.degrade_order",
            ),
        ),
        translation=TranslationConfig(
            pass3_default=_as_bool(
                translation.get("pass3_default", TranslationConfig().pass3_default),
                "translation.pass3_default",
            ),
            risk_threshold_high=_as_float(
                translation.get(
                    "risk_threshold_high",
                    TranslationConfig().risk_threshold_high,
                ),
                "translation.risk_threshold_high",
            ),
            batched_model_order=_as_bool(
                translation.get(
                    "batched_model_order",
                    TranslationConfig().batched_model_order,
                ),
                "translation.batched_model_order",
            ),
        ),
        summaries=SummariesConfig(
            exclude_chapter_patterns=_as_str_list(
                summaries.get(
                    "exclude_chapter_patterns",
                    SummariesConfig().exclude_chapter_patterns,
                ),
                "summaries.exclude_chapter_patterns",
            ),
        ),
        events=EventsConfig(
            persistence_mode=_as_str(
                events.get("persistence_mode", EventsConfig().persistence_mode),
                "events.persistence_mode",
            ),
            progress_sample_every=_as_int(
                events.get("progress_sample_every", EventsConfig().progress_sample_every),
                "events.progress_sample_every",
            ),
        ),
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    if not config.models.translator_name.strip():
        raise ValueError("models.translator_name is required.")
    if not config.models.analyst_name.strip():
        raise ValueError("models.analyst_name is required.")
    if not config.models.embedding_name.strip():
        raise ValueError("models.embedding_name is required.")

    if config.budget.max_context_per_pass <= 0:
        raise ValueError("budget.max_context_per_pass must be > 0.")
    if config.budget.max_paragraph_chars <= 0:
        raise ValueError("budget.max_paragraph_chars must be > 0.")
    if config.budget.max_bundle_bytes <= 0:
        raise ValueError("budget.max_bundle_bytes must be > 0.")
    if config.llm.timeout_seconds <= 0:
        raise ValueError("llm.timeout_seconds must be > 0.")
    if config.llm.max_retries < 0:
        raise ValueError("llm.max_retries must be >= 0.")
    if config.translation.risk_threshold_high < 0 or config.translation.risk_threshold_high > 1:
        raise ValueError("translation.risk_threshold_high must be in [0.0, 1.0].")
    if config.events.persistence_mode not in {"normal", "reduced"}:
        raise ValueError("events.persistence_mode must be 'normal' or 'reduced'.")
    if config.events.progress_sample_every <= 0:
        raise ValueError("events.progress_sample_every must be > 0.")
    if not config.paths.artifact_root.strip():
        raise ValueError("paths.artifact_root must not be empty.")
    if not config.paths.db_filename.strip():
        raise ValueError("paths.db_filename must not be empty.")


def derive_paths(
    config: AppConfig,
    release_id: str,
    project_root: Path | None = None,
) -> DerivedPaths:
    if not release_id.strip():
        raise ValueError("release_id must not be empty.")

    root = (project_root or Path.cwd()).resolve()
    artifact_root = (root / config.paths.artifact_root).resolve()
    release_root = artifact_root / "releases" / release_id
    extracted_root = release_root / "extracted"

    return DerivedPaths(
        project_root=root,
        artifact_root=artifact_root,
        release_root=release_root,
        unpacked_dir=release_root / "work" / "unpacked",
        extracted_chapters_dir=extracted_root / "chapters",
        extracted_chapter_manifest_path=extracted_root / "chapter-manifest.json",
        extracted_reports_dir=extracted_root / "reports",
        extracted_placeholders_dir=extracted_root / "placeholders",
        glossary_dir=release_root / "glossary",
        glossary_candidates_path=release_root / "glossary" / "candidates.json",
        glossary_conflicts_path=release_root / "glossary" / "conflicts.json",
        idioms_dir=release_root / "idioms",
        idiom_candidates_path=release_root / "idioms" / "candidates.json",
        idiom_policies_path=release_root / "idioms" / "policies.json",
        idiom_conflicts_path=release_root / "idioms" / "conflicts.json",
        summaries_dir=release_root / "summaries",
        graph_dir=release_root / "graph",
        graph_snapshot_path=release_root / "graph" / "snapshot.json",
        graph_warnings_path=release_root / "graph" / "warnings.json",
        graph_db_path=artifact_root / "graph.ladybug",
        packets_dir=release_root / "packets",
        rebuilt_epub_path=release_root / "rebuild" / "reconstructed.epub",
        db_path=artifact_root / config.paths.db_filename,
    )
