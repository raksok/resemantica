from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ModelsConfig:
    translator_name: str = "HY-MT1.5-7B"
    preprocess_translator_names: list[str] = field(default_factory=list)
    translator_context_window: int | None = None
    translator_max_context_ratio: float | None = None
    analyst_name: str = "Qwen3.5-9B-GLM5.1"
    analyst_context_window: int | None = None
    analyst_max_context_ratio: float | None = None
    eval_name: str = "Qwen3.5-9B-GLM5.1"
    embedding_name: str = "BAAI/bge-m3"
    pruning_threshold: float = 0.3

    def effective_preprocess_translator_names(self) -> list[str]:
        configured = [name.strip() for name in self.preprocess_translator_names if name.strip()]
        if configured:
            return configured
        return [self.translator_name]

    def effective_context_window(self, role: str, global_window: int) -> int:
        if role == "translator":
            return self.translator_context_window or global_window
        if role == "analyst":
            return self.analyst_context_window or global_window
        raise ValueError(f"Unknown model role: {role}")

    def effective_max_context_per_pass(self, role: str, global_budget: int, global_window: int) -> int:
        if role == "translator":
            has_custom = self.translator_context_window is not None
            window = self.translator_context_window or global_window
            ratio = self.translator_max_context_ratio or 0.75
        elif role == "analyst":
            has_custom = self.analyst_context_window is not None
            window = self.analyst_context_window or global_window
            ratio = self.analyst_max_context_ratio or 0.75
        else:
            raise ValueError(f"Unknown model role: {role}")
        if has_custom:
            return int(window * ratio)
        return global_budget


@dataclass(slots=True)
class LLMThrottleGroupConfig:
    model_names: list[str] = field(default_factory=list)
    max_concurrent_requests: int = 1
    system_prompt: str = ""


@dataclass(slots=True)
class LLMConfig:
    base_url: str = "http://localhost:8080"
    timeout_seconds: int = 300
    max_retries: int = 2
    context_window: int = 65536
    max_concurrent_requests_per_model: int = 1
    throttle_groups: dict[str, LLMThrottleGroupConfig] = field(default_factory=dict)


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
    pass3_default: bool = False
    risk_threshold_high: float = 0.7
    batched_model_order: bool = True
    pass2_concurrency: int = 2


@dataclass(slots=True)
class BatchOrderConfig:
    enabled: bool = True
    summary_chunk_multiplier: int = 10
    translation_chunk_size: int = 10


@dataclass(slots=True)
class SummariesConfig:
    exclude_chapter_patterns: list[str] = field(default_factory=list)
    chapter_concurrency: int = 1
    story_compact_max_tokens: int = 2048
    graph_continuity_rebase_interval: int = 50


@dataclass(slots=True)
class EventsConfig:
    persistence_mode: str = "normal"
    progress_sample_every: int = 25


@dataclass(slots=True)
class PacketConfig:
    budget_tokens: int | None = None
    max_bundle_bytes: int = 4096
    max_paragraph_chars: int = 2000


@dataclass(slots=True)
class GlossaryResolutionAliasFamily:
    source_contains: str
    preferred: str
    variants: list[str] = field(default_factory=list)


def _default_glossary_resolution_alias_families() -> list[GlossaryResolutionAliasFamily]:
    return [
        GlossaryResolutionAliasFamily(
            source_contains="大骊",
            preferred="Great Li",
            variants=["Great Li", "Da Li", "Dali", "Dalí"],
        ),
        GlossaryResolutionAliasFamily(
            source_contains="大隋",
            preferred="Great Sui",
            variants=["Great Sui", "Da Sui", "Dasiu"],
        ),
    ]


@dataclass(slots=True)
class GlossaryConfig:
    min_term_length: int = 2
    max_term_length: int = 20
    min_corpus_score: float = 0.1
    eval_batch_size: int = 50
    dedup_similarity_threshold: float = 0.85
    resolution_alias_families: list[GlossaryResolutionAliasFamily] = field(
        default_factory=_default_glossary_resolution_alias_families
    )


@dataclass(slots=True)
class AppConfig:
    models: ModelsConfig = field(default_factory=ModelsConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    batch_order: BatchOrderConfig = field(default_factory=BatchOrderConfig)
    summaries: SummariesConfig = field(default_factory=SummariesConfig)
    events: EventsConfig = field(default_factory=EventsConfig)
    glossary: GlossaryConfig = field(default_factory=GlossaryConfig)
    packets: PacketConfig = field(default_factory=PacketConfig)


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
    glossary_review_path: Path
    idioms_dir: Path
    idiom_candidates_path: Path
    idiom_policies_path: Path
    idiom_conflicts_path: Path
    idiom_review_path: Path
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
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"{field_name} must be an integer.") from None
    raise ValueError(f"{field_name} must be an integer.")


def _as_float(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric.")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"{field_name} must be numeric.") from None
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


def _parse_llm_throttle_groups(llm: dict[str, object]) -> dict[str, LLMThrottleGroupConfig]:
    raw_groups = llm.get("throttle_groups", {})
    if not isinstance(raw_groups, dict):
        raise ValueError("llm.throttle_groups must be a table.")
    parsed: dict[str, LLMThrottleGroupConfig] = {}
    for group_name, raw_group in raw_groups.items():
        if not isinstance(group_name, str) or not group_name.strip():
            raise ValueError("llm.throttle_groups keys must be non-empty strings.")
        if not isinstance(raw_group, dict):
            raise ValueError(f"llm.throttle_groups.{group_name} must be a table.")
        parsed[group_name] = LLMThrottleGroupConfig(
            model_names=_as_str_list(
                raw_group.get("model_names", LLMThrottleGroupConfig().model_names),
                f"llm.throttle_groups.{group_name}.model_names",
            ),
            max_concurrent_requests=_as_int(
                raw_group.get(
                    "max_concurrent_requests",
                    LLMThrottleGroupConfig().max_concurrent_requests,
                ),
                f"llm.throttle_groups.{group_name}.max_concurrent_requests",
            ),
            system_prompt=_as_str(
                raw_group.get("system_prompt", LLMThrottleGroupConfig().system_prompt),
                f"llm.throttle_groups.{group_name}.system_prompt",
            ),
        )
    return parsed


def _parse_glossary_resolution_alias_families(
    glossary: dict[str, object],
) -> list[GlossaryResolutionAliasFamily]:
    raw_families = glossary.get(
        "resolution_alias_families",
        GlossaryConfig().resolution_alias_families,
    )
    if not isinstance(raw_families, list):
        raise ValueError("glossary.resolution_alias_families must be a list of tables.")
    parsed: list[GlossaryResolutionAliasFamily] = []
    for index, raw_family in enumerate(raw_families):
        field_prefix = f"glossary.resolution_alias_families[{index}]"
        if isinstance(raw_family, GlossaryResolutionAliasFamily):
            parsed.append(
                GlossaryResolutionAliasFamily(
                    source_contains=raw_family.source_contains,
                    preferred=raw_family.preferred,
                    variants=list(raw_family.variants),
                )
            )
            continue
        if not isinstance(raw_family, dict):
            raise ValueError(f"{field_prefix} must be a table.")
        parsed.append(
            GlossaryResolutionAliasFamily(
                source_contains=_as_str(
                    raw_family.get("source_contains", ""),
                    f"{field_prefix}.source_contains",
                ),
                preferred=_as_str(
                    raw_family.get("preferred", ""),
                    f"{field_prefix}.preferred",
                ),
                variants=_as_str_list(
                    raw_family.get("variants", []),
                    f"{field_prefix}.variants",
                ),
            )
        )
    return parsed


def load_config(config_path: Path | None = None) -> AppConfig:
    resolved_path = config_path or Path.cwd() / "resemantica.toml"
    raw = _read_toml(resolved_path)

    models = _table(raw, "models")
    llm = _table(raw, "llm")
    paths = _table(raw, "paths")
    budget = _table(raw, "budget")
    translation = _table(raw, "translation")
    batch_order = _table(raw, "batch_order")
    summaries = _table(raw, "summaries")
    events = _table(raw, "events")
    glossary = _table(raw, "glossary")
    packets = _table(raw, "packets")

    config = AppConfig(
        models=ModelsConfig(
            translator_name=_as_str(
                models.get("translator_name", ModelsConfig().translator_name),
                "models.translator_name",
            ),
            preprocess_translator_names=_as_str_list(
                models.get(
                    "preprocess_translator_names",
                    ModelsConfig().preprocess_translator_names,
                ),
                "models.preprocess_translator_names",
            ),
            translator_context_window=(
                _as_int(models["translator_context_window"], "models.translator_context_window")
                if "translator_context_window" in models else None
            ),
            translator_max_context_ratio=(
                _as_float(models["translator_max_context_ratio"], "models.translator_max_context_ratio")
                if "translator_max_context_ratio" in models else None
            ),
            analyst_name=_as_str(
                models.get("analyst_name", ModelsConfig().analyst_name),
                "models.analyst_name",
            ),
            eval_name=_as_str(
                models.get("eval_name", ModelsConfig().eval_name),
                "models.eval_name",
            ),
            analyst_context_window=(
                _as_int(models["analyst_context_window"], "models.analyst_context_window")
                if "analyst_context_window" in models else None
            ),
            analyst_max_context_ratio=(
                _as_float(models["analyst_max_context_ratio"], "models.analyst_max_context_ratio")
                if "analyst_max_context_ratio" in models else None
            ),
            embedding_name=_as_str(
                models.get("embedding_name", ModelsConfig().embedding_name),
                "models.embedding_name",
            ),
            pruning_threshold=_as_float(
                models.get("pruning_threshold", ModelsConfig().pruning_threshold),
                "models.pruning_threshold",
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
            max_concurrent_requests_per_model=_as_int(
                llm.get(
                    "max_concurrent_requests_per_model",
                    LLMConfig().max_concurrent_requests_per_model,
                ),
                "llm.max_concurrent_requests_per_model",
            ),
            throttle_groups=_parse_llm_throttle_groups(llm),
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
            pass2_concurrency=_as_int(
                translation.get(
                    "pass2_concurrency",
                    TranslationConfig().pass2_concurrency,
                ),
                "translation.pass2_concurrency",
            ),
        ),
        batch_order=BatchOrderConfig(
            enabled=_as_bool(
                batch_order.get("enabled", BatchOrderConfig().enabled),
                "batch_order.enabled",
            ),
            summary_chunk_multiplier=_as_int(
                batch_order.get(
                    "summary_chunk_multiplier",
                    BatchOrderConfig().summary_chunk_multiplier,
                ),
                "batch_order.summary_chunk_multiplier",
            ),
            translation_chunk_size=_as_int(
                batch_order.get(
                    "translation_chunk_size",
                    BatchOrderConfig().translation_chunk_size,
                ),
                "batch_order.translation_chunk_size",
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
            chapter_concurrency=_as_int(
                summaries.get(
                    "chapter_concurrency",
                    SummariesConfig().chapter_concurrency,
                ),
                "summaries.chapter_concurrency",
            ),
            story_compact_max_tokens=_as_int(
                summaries.get(
                    "story_compact_max_tokens",
                    SummariesConfig().story_compact_max_tokens,
                ),
                "summaries.story_compact_max_tokens",
            ),
            graph_continuity_rebase_interval=_as_int(
                summaries.get(
                    "graph_continuity_rebase_interval",
                    SummariesConfig().graph_continuity_rebase_interval,
                ),
                "summaries.graph_continuity_rebase_interval",
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
        glossary=GlossaryConfig(
            min_term_length=_as_int(
                glossary.get("min_term_length", GlossaryConfig().min_term_length),
                "glossary.min_term_length",
            ),
            max_term_length=_as_int(
                glossary.get("max_term_length", GlossaryConfig().max_term_length),
                "glossary.max_term_length",
            ),
            min_corpus_score=_as_float(
                glossary.get("min_corpus_score", GlossaryConfig().min_corpus_score),
                "glossary.min_corpus_score",
            ),
            eval_batch_size=_as_int(
                glossary.get("eval_batch_size", GlossaryConfig().eval_batch_size),
                "glossary.eval_batch_size",
            ),
            dedup_similarity_threshold=_as_float(
                glossary.get("dedup_similarity_threshold", GlossaryConfig().dedup_similarity_threshold),
                "glossary.dedup_similarity_threshold",
            ),
            resolution_alias_families=_parse_glossary_resolution_alias_families(glossary),
        ),
        packets=PacketConfig(
            budget_tokens=(
                _as_int(packets["budget_tokens"], "packets.budget_tokens")
                if "budget_tokens" in packets else None
            ),
            max_bundle_bytes=_as_int(
                packets.get("max_bundle_bytes", PacketConfig().max_bundle_bytes),
                "packets.max_bundle_bytes",
            ),
            max_paragraph_chars=_as_int(
                packets.get("max_paragraph_chars", PacketConfig().max_paragraph_chars),
                "packets.max_paragraph_chars",
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
    if not config.models.eval_name.strip():
        raise ValueError("models.eval_name is required.")
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
    if config.llm.max_concurrent_requests_per_model < 1:
        raise ValueError("llm.max_concurrent_requests_per_model must be >= 1.")
    seen_throttle_models: dict[str, str] = {}
    for group_name, group in config.llm.throttle_groups.items():
        if group.max_concurrent_requests < 1:
            raise ValueError(
                f"llm.throttle_groups.{group_name}.max_concurrent_requests must be >= 1."
            )
        normalized_models = [model.strip() for model in group.model_names if model.strip()]
        if not normalized_models:
            raise ValueError(f"llm.throttle_groups.{group_name}.model_names must not be empty.")
        if len(normalized_models) != len(set(normalized_models)):
            raise ValueError(f"llm.throttle_groups.{group_name}.model_names contains duplicates.")
        group.model_names = normalized_models
        for model_name in normalized_models:
            existing_group = seen_throttle_models.get(model_name)
            if existing_group is not None:
                raise ValueError(
                    f"llm.throttle_groups model {model_name!r} appears in both "
                    f"{existing_group!r} and {group_name!r}."
                )
            seen_throttle_models[model_name] = group_name
    if config.translation.risk_threshold_high < 0 or config.translation.risk_threshold_high > 1:
        raise ValueError("translation.risk_threshold_high must be in [0.0, 1.0].")
    if config.events.persistence_mode not in {"normal", "reduced"}:
        raise ValueError("events.persistence_mode must be 'normal' or 'reduced'.")
    if config.translation.pass2_concurrency < 1:
        raise ValueError("translation.pass2_concurrency must be >= 1.")
    if config.batch_order.summary_chunk_multiplier <= 0:
        raise ValueError("batch_order.summary_chunk_multiplier must be > 0.")
    if config.batch_order.translation_chunk_size <= 0:
        raise ValueError("batch_order.translation_chunk_size must be > 0.")
    if config.summaries.chapter_concurrency < 1 or config.summaries.chapter_concurrency > 5:
        raise ValueError("summaries.chapter_concurrency must be in [1, 5].")
    if config.summaries.story_compact_max_tokens <= 0:
        raise ValueError("summaries.story_compact_max_tokens must be > 0.")
    if config.summaries.graph_continuity_rebase_interval <= 0:
        raise ValueError("summaries.graph_continuity_rebase_interval must be > 0.")
    if config.models.pruning_threshold < 0 or config.models.pruning_threshold > 1:
        raise ValueError("models.pruning_threshold must be in [0.0, 1.0].")
    if config.events.progress_sample_every <= 0:
        raise ValueError("events.progress_sample_every must be > 0.")
    for role in ("translator", "analyst"):
        cw = getattr(config.models, f"{role}_context_window")
        if cw is not None and cw <= 0:
            raise ValueError(f"models.{role}_context_window must be > 0 when set")
        r = getattr(config.models, f"{role}_max_context_ratio")
        if r is not None and not (0 < r <= 1):
            raise ValueError(f"models.{role}_max_context_ratio must be in (0, 1] when set")

    if config.glossary.min_term_length < 1:
        raise ValueError("glossary.min_term_length must be >= 1.")
    if config.glossary.max_term_length < config.glossary.min_term_length:
        raise ValueError("glossary.max_term_length must be >= glossary.min_term_length.")
    if config.glossary.min_corpus_score < 0:
        raise ValueError("glossary.min_corpus_score must be >= 0.")
    if config.glossary.eval_batch_size < 1:
        raise ValueError("glossary.eval_batch_size must be >= 1.")
    if not (0 <= config.glossary.dedup_similarity_threshold <= 1):
        raise ValueError("glossary.dedup_similarity_threshold must be in [0.0, 1.0].")
    for index, family in enumerate(config.glossary.resolution_alias_families):
        prefix = f"glossary.resolution_alias_families[{index}]"
        family.source_contains = family.source_contains.strip()
        family.preferred = family.preferred.strip()
        family.variants = [variant.strip() for variant in family.variants if variant.strip()]
        if not family.source_contains:
            raise ValueError(f"{prefix}.source_contains must not be empty.")
        if not family.preferred:
            raise ValueError(f"{prefix}.preferred must not be empty.")
        if not family.variants:
            raise ValueError(f"{prefix}.variants must not be empty.")

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
        glossary_review_path=release_root / "glossary" / "review.json",
        idioms_dir=release_root / "idioms",
        idiom_candidates_path=release_root / "idioms" / "candidates.json",
        idiom_policies_path=release_root / "idioms" / "policies.json",
        idiom_conflicts_path=release_root / "idioms" / "conflicts.json",
        idiom_review_path=release_root / "idioms" / "review.json",
        summaries_dir=release_root / "summaries",
        graph_dir=release_root / "graph",
        graph_snapshot_path=release_root / "graph" / "snapshot.json",
        graph_warnings_path=release_root / "graph" / "warnings.json",
        graph_db_path=release_root / "graph.ladybug",
        packets_dir=release_root / "packets",
        rebuilt_epub_path=release_root / "rebuild" / "reconstructed.epub",
        db_path=release_root / config.paths.db_filename,
    )
