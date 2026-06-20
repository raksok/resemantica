from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from loguru import logger

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.db.glossary_repo import list_locked_entries
from resemantica.db.graph_repo import list_graph_snapshots
from resemantica.db.sqlite import ensure_schema, open_connection
from resemantica.db.summary_repo import (
    ValidatedSummaryZhRecord,
    get_validated_summary,
    list_validated_summaries,
    save_derived_summary,
    save_validated_summary,
)
from resemantica.graph.client import GraphClient
from resemantica.llm.budget import ensure_prompt_within_budget
from resemantica.llm.cache import LLMCacheIdentity, hash_prompt, load_cached_text, save_cached_text
from resemantica.llm.client import (
    LLMClient,
    capture_usage_snapshot,
    record_cache_hit,
    usage_payload_delta,
)
from resemantica.llm.prompts import PromptTemplate, load_prompt, render_named_sections
from resemantica.llm.tokens import count_tokens
from resemantica.orchestration.stop import StopRequested, StopToken, raise_if_stop_requested
from resemantica.settings import AppConfig, derive_paths, load_config
from resemantica.summaries.derivation import (
    derive_english_summary,
    hash_locked_glossary,
    hash_validated_summary,
)
from resemantica.utils import _build_llm_client, _canonical_json, _write_json
from resemantica.utils import _emit as _emit_shared

_STAGE_NAME = "preprocess-continuity"
_RECENT_SUMMARY_WINDOW = 3


@dataclass(slots=True)
class GraphContinuityInput:
    previous_graph_compact: str
    recent_chapter_summaries: list[ValidatedSummaryZhRecord]
    current_chapter_number: int
    graph_anchors_zh: str
    graph_anchor_audit: dict[str, object]
    source_hash: str


def _emit(run_id: str, release_id: str, event_type: str, **kwargs: object) -> None:
    _emit_shared(run_id, release_id, event_type, stage_name=_STAGE_NAME, **kwargs)


def _build_graph_client(paths: Any, graph_client: GraphClient | None) -> GraphClient:
    if graph_client is not None:
        return graph_client
    return GraphClient.from_ladybug(db_path=paths.graph_db_path)


def _parse_json_object(raw_output: str) -> dict[str, Any]:
    text = raw_output.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 :] if first_newline != -1 else text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()
        if text.startswith("json"):
            text = text[4:].strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("graph_continuity_output_invalid: expected JSON object")
    return parsed


def _anchor_entity_name(entity_id: str, entity_names: dict[str, str]) -> str:
    return entity_names.get(entity_id, entity_id)


def build_graph_continuity_anchors(
    *,
    graph_client: GraphClient,
    chapter_number: int,
) -> tuple[str, dict[str, object]]:
    subgraph = graph_client.get_chapter_safe_subgraph(chapter_number=chapter_number)
    entities = sorted(subgraph["entities"], key=lambda row: row.entity_id)
    aliases = sorted(subgraph["aliases"], key=lambda row: (row.entity_id, row.alias_text, row.alias_id))
    appearances = sorted(
        subgraph["appearances"],
        key=lambda row: (row.entity_id, row.chapter_number, row.appearance_id),
    )
    relationships = sorted(subgraph["relationships"], key=lambda row: row.relationship_id)
    entity_names = {row.entity_id: row.canonical_name for row in entities}

    aliases_by_entity: dict[str, list[str]] = {}
    for alias in aliases:
        aliases_by_entity.setdefault(alias.entity_id, []).append(alias.alias_text)

    appearances_by_entity: dict[str, list[int]] = {}
    for appearance in appearances:
        appearances_by_entity.setdefault(appearance.entity_id, []).append(appearance.chapter_number)

    lines: list[str] = []
    if entities:
        lines.append("实体锚点：")
        for entity in entities:
            alias_text = "、".join(dict.fromkeys(aliases_by_entity.get(entity.entity_id, [])))
            seen = sorted(set(appearances_by_entity.get(entity.entity_id, [])))
            seen_text = f"出场至第{seen[-1]}章" if seen else f"首次第{entity.first_seen_chapter}章"
            alias_suffix = f"，别名：{alias_text}" if alias_text else ""
            lines.append(
                f"- {entity.canonical_name}（{entity.entity_type}，{seen_text}，"
                f"揭示第{entity.revealed_chapter}章{alias_suffix}）"
            )

    if relationships:
        lines.append("关系锚点：")
        for rel in relationships:
            source_name = _anchor_entity_name(rel.source_entity_id, entity_names)
            target_name = _anchor_entity_name(rel.target_entity_id, entity_names)
            lore_suffix = f"，已揭示：{rel.lore_text.strip()}" if rel.lore_text else ""
            lines.append(
                f"- {source_name} {rel.type} {target_name}（第{rel.start_chapter}章起，"
                f"揭示第{rel.revealed_chapter}章{lore_suffix}）"
            )

    if not lines:
        lines.append("无已确认且章节安全的图谱锚点。")

    audit = {
        "chapter_number": chapter_number,
        "entity_ids": [row.entity_id for row in entities],
        "alias_ids": [row.alias_id for row in aliases],
        "appearance_ids": [row.appearance_id for row in appearances],
        "relationship_ids": [row.relationship_id for row in relationships],
        "entity_count": len(entities),
        "alias_count": len(aliases),
        "appearance_count": len(appearances),
        "relationship_count": len(relationships),
    }
    return "\n".join(lines), audit


def _milestone_base_record(
    records: list[ValidatedSummaryZhRecord],
    *,
    chapter_number: int,
    rebase_interval: int,
) -> ValidatedSummaryZhRecord | None:
    if rebase_interval <= 0 or chapter_number % rebase_interval != 0:
        prior = [row for row in records if row.chapter_number < chapter_number]
        return prior[-1] if prior else None
    milestone_floor = chapter_number - rebase_interval
    milestone_records = [
        row
        for row in records
        if row.chapter_number <= milestone_floor
        and row.chapter_number % rebase_interval == 0
    ]
    if milestone_records:
        return milestone_records[-1]
    prior = [row for row in records if row.chapter_number < chapter_number]
    return prior[-1] if prior else None


def build_graph_continuity_input(
    *,
    conn: Any,
    release_id: str,
    chapter_number: int,
    graph_client: GraphClient,
    rebase_interval: int,
) -> GraphContinuityInput:
    prior_graph_compacts = list_validated_summaries(
        conn,
        release_id=release_id,
        summary_type="story_so_far_zh_graph_compact",
        max_chapter_number=chapter_number - 1,
    )
    base = _milestone_base_record(
        prior_graph_compacts,
        chapter_number=chapter_number,
        rebase_interval=rebase_interval,
    )
    previous_text = base.content_zh if base is not None else ""
    base_chapter = base.chapter_number if base is not None else 0
    recent = list_validated_summaries(
        conn,
        release_id=release_id,
        summary_type="chapter_summary_zh_short",
        max_chapter_number=chapter_number,
    )
    if chapter_number % rebase_interval == 0 and rebase_interval > 0:
        recent = [row for row in recent if row.chapter_number > base_chapter]
    else:
        recent = [row for row in recent if row.chapter_number <= chapter_number]
        recent = recent[-_RECENT_SUMMARY_WINDOW:]

    anchors, audit = build_graph_continuity_anchors(
        graph_client=graph_client,
        chapter_number=chapter_number,
    )
    audit["base_chapter_number"] = base_chapter
    audit["recent_summary_chapters"] = [row.chapter_number for row in recent]
    source_payload = {
        "previous_graph_compact": previous_text,
        "recent_summaries": [
            {
                "chapter_number": row.chapter_number,
                "summary_id": row.summary_id,
                "content_zh": row.content_zh,
                "derived_from_chapter_hash": row.derived_from_chapter_hash,
            }
            for row in recent
        ],
        "graph_anchors_zh": anchors,
        "graph_anchor_audit": audit,
    }
    return GraphContinuityInput(
        previous_graph_compact=previous_text,
        recent_chapter_summaries=recent,
        current_chapter_number=chapter_number,
        graph_anchors_zh=anchors,
        graph_anchor_audit=audit,
        source_hash=sha256(_canonical_json(source_payload).encode("utf-8")).hexdigest(),
    )


def _format_recent_summaries(rows: list[ValidatedSummaryZhRecord]) -> str:
    if not rows:
        return "无。"
    return "\n".join(f"第{row.chapter_number}章：{row.content_zh.strip()}" for row in rows if row.content_zh.strip())


def refresh_graph_continuity_text(
    *,
    llm_client: LLMClient,
    release_id: str,
    model_name: str,
    prompt: PromptTemplate,
    continuity_input: GraphContinuityInput,
    config: AppConfig,
    cache_root: Path | None,
) -> tuple[str, dict[str, object]]:
    rendered = render_named_sections(
        prompt.template,
        sections={
            "PREVIOUS_GRAPH_COMPACT": continuity_input.previous_graph_compact.strip() or "无。",
            "RECENT_CHAPTER_SUMMARIES": _format_recent_summaries(continuity_input.recent_chapter_summaries),
            "CURRENT_CHAPTER_NUMBER": str(continuity_input.current_chapter_number),
            "GRAPH_ANCHORS": continuity_input.graph_anchors_zh,
            "STORY_COMPACT_MAX_TOKENS": str(config.summaries.story_compact_max_tokens),
        },
    )
    analyst_budget = config.models.effective_max_context_per_pass(
        "analyst",
        config.budget.max_context_per_pass,
        config.llm.context_window,
    )
    ensure_prompt_within_budget(
        rendered,
        config=config,
        stage_name=f"{_STAGE_NAME}.graph-compact",
        chapter_number=continuity_input.current_chapter_number,
        max_tokens=analyst_budget,
    )
    identity = LLMCacheIdentity(
        release_id=release_id,
        chapter_number=continuity_input.current_chapter_number,
        source_hash=continuity_input.source_hash,
        stage_name=f"{_STAGE_NAME}.graph-compact",
        chunk_index=1,
        model_name=model_name,
        prompt_version=prompt.version,
        prompt_hash=hash_prompt(rendered),
    )
    cached = load_cached_text(cache_root, identity) if cache_root is not None else None
    if cached is not None:
        record_cache_hit(llm_client)
    raw_output = (
        cached
        if cached is not None
        else llm_client.generate_text(model_name=model_name, prompt=rendered).strip()
    )
    if cache_root is not None and cached is None:
        save_cached_text(cache_root, identity, raw_output)

    parsed = _parse_json_object(raw_output)
    compact = str(parsed.get("continuity_zh", "")).strip()
    if not compact:
        raise ValueError("story_so_far_zh_graph_compact generation returned empty continuity_zh")
    token_count = count_tokens(compact)
    if token_count > config.summaries.story_compact_max_tokens:
        raise ValueError(
            "story_so_far_zh_graph_compact exceeds configured token budget: "
            f"{token_count} > {config.summaries.story_compact_max_tokens}"
        )
    audit = parsed.get("anchor_audit", {})
    if not isinstance(audit, dict):
        raise ValueError("graph_continuity_output_invalid: anchor_audit must be an object")
    return compact, dict(audit)


def preprocess_continuity(
    *,
    release_id: str,
    run_id: str = "continuity",
    config: AppConfig | None = None,
    project_root: Path | None = None,
    graph_client: GraphClient | None = None,
    llm_client: LLMClient | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    stop_token: StopToken | None = None,
    force: bool = False,  # noqa: ARG001 - kept for stage API parity
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    chapter_refs = list_extracted_chapters(
        paths,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
    )
    if not chapter_refs:
        raise FileNotFoundError(
            f"No extracted chapters found for release {release_id}: {paths.extracted_chapters_dir}"
        )

    graph = _build_graph_client(paths, graph_client)
    client = _build_llm_client(config_obj, llm_client)
    usage_before = capture_usage_snapshot(client)
    prompt = load_prompt("summary_graph_continuity_update.txt")
    prompt_en = load_prompt("summary_en_derive.txt")

    conn = open_connection(paths.db_path)
    ensure_schema(conn, "summaries")
    ensure_schema(conn, "glossary")
    ensure_schema(conn, "graph")
    try:
        snapshots = list_graph_snapshots(conn, release_id=release_id)
        if not snapshots:
            raise RuntimeError(f"missing_graph_snapshot: release={release_id}")

        _emit(run_id, release_id, f"{_STAGE_NAME}.started", total_chapters=len(chapter_refs))
        refreshed: list[dict[str, object]] = []
        locked_glossary = list_locked_entries(conn, release_id=release_id)
        glossary_hash = hash_locked_glossary(locked_glossary)
        for ref in chapter_refs:
            chapter_number = ref.chapter_number
            raise_if_stop_requested(
                stop_token,
                checkpoint={"refreshed_chapters": [row["chapter_number"] for row in refreshed]},
                message="Continuity refresh stopped before next chapter",
            )
            if get_validated_summary(
                conn,
                release_id=release_id,
                chapter_number=chapter_number,
                summary_type="chapter_summary_zh_short",
            ) is None:
                logger.info("Chapter {} skipped: missing chapter short summary", chapter_number)
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.chapter_skipped",
                    chapter_number=chapter_number,
                    reason="missing_chapter_summary_short",
                )
                continue

            _emit(run_id, release_id, f"{_STAGE_NAME}.chapter_started", chapter_number=chapter_number)
            try:
                continuity_input = build_graph_continuity_input(
                    conn=conn,
                    release_id=release_id,
                    chapter_number=chapter_number,
                    graph_client=graph,
                    rebase_interval=config_obj.summaries.graph_continuity_rebase_interval,
                )
                compact_text, model_anchor_audit = refresh_graph_continuity_text(
                    llm_client=client,
                    release_id=release_id,
                    model_name=config_obj.models.analyst_name,
                    prompt=prompt,
                    continuity_input=continuity_input,
                    config=config_obj,
                    cache_root=paths.release_root / "cache" / "llm",
                )
                record = save_validated_summary(
                    conn,
                    release_id=release_id,
                    chapter_number=chapter_number,
                    summary_type="story_so_far_zh_graph_compact",
                    content_zh=compact_text,
                    derived_from_chapter_hash=continuity_input.source_hash,
                    run_id=run_id,
                    validation_status="approved",
                )
                en_text = derive_english_summary(
                    llm_client=client,
                    model_name=config_obj.models.translator_name,
                    prompt_template=prompt_en.template,
                    source_text_zh=compact_text,
                    locked_glossary=locked_glossary,
                    config=config_obj,
                    stage_name=f"{_STAGE_NAME}.graph-compact-en",
                    chapter_number=chapter_number,
                )
                en_record = save_derived_summary(
                    conn,
                    release_id=release_id,
                    chapter_number=chapter_number,
                    summary_type="story_so_far_en_graph_compact",
                    content_en=en_text,
                    source_summary_id=record.summary_id,
                    source_summary_hash=hash_validated_summary(record),
                    glossary_version_hash=glossary_hash,
                    model_name=config_obj.models.translator_name,
                    prompt_version=prompt_en.version,
                    run_id=run_id,
                )
                artifact_path = paths.summaries_dir / f"chapter-{chapter_number}-graph-continuity.json"
                _write_json(
                    artifact_path,
                    {
                        "release_id": release_id,
                        "run_id": run_id,
                        "chapter_number": chapter_number,
                        "schema_version": 1,
                        "validated": {
                            "story_so_far_zh_graph_compact": record.to_json_dict(),
                        },
                        "derived": {
                            "story_so_far_en_graph_compact": en_record.to_json_dict(),
                        },
                        "graph_anchor_audit": continuity_input.graph_anchor_audit,
                        "model_anchor_audit": model_anchor_audit,
                        "graph_anchors_zh": continuity_input.graph_anchors_zh,
                    },
                )
                refreshed.append(
                    {
                        "chapter_number": chapter_number,
                        "summary_id": record.summary_id,
                        "artifact": str(artifact_path),
                        "anchor_count": continuity_input.graph_anchor_audit["entity_count"],
                    }
                )
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.chapter_completed",
                    chapter_number=chapter_number,
                    summary_id=record.summary_id,
                    artifact_path=str(artifact_path),
                )
                raise_if_stop_requested(
                    stop_token,
                    checkpoint={"refreshed_chapters": [row["chapter_number"] for row in refreshed]},
                    message=f"Continuity refresh stopped after chapter {chapter_number}",
                )
            except StopRequested:
                raise
            except Exception as exc:
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.chapter_failed",
                    chapter_number=chapter_number,
                    severity="error",
                    message=f"Continuity refresh failed for chapter {chapter_number}: {exc}",
                    reason=str(exc),
                )
                raise
    finally:
        conn.close()

    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.completed",
        refreshed=len(refreshed),
        **usage_payload_delta(client, usage_before),
    )
    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "chapters_refreshed": len(refreshed),
        "chapter_artifacts": refreshed,
        **usage_payload_delta(client, usage_before),
    }
