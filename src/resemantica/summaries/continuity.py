from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    list_derived_summaries,
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
from resemantica.orchestration.chunk_checkpoints import (
    load_chunk_checkpoint,
    save_chunk_checkpoint,
)
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
_MAX_GRAPH_CONTINUITY_ATTEMPTS = 4
_GRAPH_CONTINUITY_ANCHOR_MAX_TOKENS = 12_000
_MAX_ALIASES_PER_ANCHOR_ENTITY = 6


@dataclass(slots=True)
class GraphContinuityInput:
    previous_graph_compact: str
    recent_chapter_summaries: list[ValidatedSummaryZhRecord]
    current_chapter_number: int
    graph_anchors_zh: str
    graph_anchor_audit: dict[str, object]
    source_hash: str


@dataclass(slots=True)
class _GraphContinuityZhResult:
    chapter_number: int
    continuity_input: GraphContinuityInput
    record: ValidatedSummaryZhRecord
    model_anchor_audit: dict[str, object]
    artifact_path: Path


@dataclass(slots=True)
class _GraphContinuityEnResult:
    chapter_number: int
    record: ValidatedSummaryZhRecord
    en_record: Any
    artifact_path: Path


def _emit(run_id: str, release_id: str, event_type: str, **kwargs: object) -> None:
    _emit_shared(run_id, release_id, event_type, stage_name=_STAGE_NAME, **kwargs)


def _build_graph_client(paths: Any, graph_client: GraphClient | None) -> GraphClient:
    if graph_client is not None:
        return graph_client
    return GraphClient.from_ladybug(db_path=paths.graph_db_path)


def _parse_json_object(raw_output: str) -> dict[str, Any]:
    text = raw_output.strip()
    if not text:
        raise ValueError("graph_continuity_output_invalid: empty model output")
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 :] if first_newline != -1 else text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("graph_continuity_output_invalid: expected JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("graph_continuity_output_invalid: expected JSON object")
    return parsed


def _validate_graph_continuity_output(raw_output: str, *, config: AppConfig) -> tuple[str, dict[str, object]]:
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


def _anchor_entity_name(entity_id: str, entity_names: dict[str, str]) -> str:
    return entity_names.get(entity_id, entity_id)


def _ordered_graph_anchor_rows(
    subgraph: dict[str, list[Any]],
) -> tuple[list[Any], list[Any], list[Any], list[Any]]:
    entities = sorted(subgraph["entities"], key=lambda row: row.entity_id)
    aliases = sorted(subgraph["aliases"], key=lambda row: (row.entity_id, row.alias_text, row.alias_id))
    appearances = sorted(
        subgraph["appearances"],
        key=lambda row: (row.entity_id, row.chapter_number, row.appearance_id),
    )
    relationships = sorted(subgraph["relationships"], key=lambda row: row.relationship_id)
    return entities, aliases, appearances, relationships


def _append_anchor_line(
    lines: list[str],
    line: str,
    *,
    max_tokens: int | None,
) -> bool:
    if max_tokens is None:
        lines.append(line)
        return True
    candidate = "\n".join([*lines, line])
    if count_tokens(candidate) > max_tokens:
        return False
    lines.append(line)
    return True


def _graph_anchor_audit(
    *,
    chapter_number: int,
    entities: list[Any],
    aliases: list[Any],
    appearances: list[Any],
    relationships: list[Any],
) -> dict[str, object]:
    return {
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


def build_graph_continuity_anchors(
    *,
    graph_client: GraphClient,
    chapter_number: int,
    recent_summary_chapters: list[int] | None = None,
    max_anchor_tokens: int | None = None,
    _raw_anchor_text_for_audit: str | None = None,
) -> tuple[str, dict[str, object]]:
    subgraph = graph_client.get_chapter_safe_subgraph(chapter_number=chapter_number)
    entities, aliases, appearances, relationships = _ordered_graph_anchor_rows(subgraph)
    raw_audit = _graph_anchor_audit(
        chapter_number=chapter_number,
        entities=entities,
        aliases=aliases,
        appearances=appearances,
        relationships=relationships,
    )

    selected_recent_chapters = set(recent_summary_chapters or [])
    if max_anchor_tokens is not None and selected_recent_chapters:
        recent_entity_ids = {
            row.entity_id
            for row in appearances
            if row.chapter_number in selected_recent_chapters
        }
        if recent_entity_ids:
            entities = sorted(
                entities,
                key=lambda row: (
                    row.entity_id not in recent_entity_ids,
                    -row.last_seen_chapter,
                    row.canonical_name,
                    row.entity_id,
                ),
            )
            relationships = sorted(
                relationships,
                key=lambda row: (
                    not (
                        row.source_entity_id in recent_entity_ids
                        and row.target_entity_id in recent_entity_ids
                    ),
                    not (
                        row.source_entity_id in recent_entity_ids
                        or row.target_entity_id in recent_entity_ids
                    ),
                    -max(row.source_chapter, row.start_chapter, row.revealed_chapter),
                    -row.confidence,
                    row.relationship_id,
                ),
            )
    else:
        recent_entity_ids = set()

    entity_names = {row.entity_id: row.canonical_name for row in entities}

    aliases_by_entity: dict[str, list[str]] = {}
    for alias in aliases:
        aliases_by_entity.setdefault(alias.entity_id, []).append(alias.alias_text)

    appearances_by_entity: dict[str, list[int]] = {}
    for appearance in appearances:
        appearances_by_entity.setdefault(appearance.entity_id, []).append(appearance.chapter_number)

    lines: list[str] = []
    selected_entities: list[Any] = []
    selected_alias_ids: set[str] = set()
    selected_entity_ids: set[str] = set()
    if entities:
        entity_lines: list[str] = []
        for entity in entities:
            if max_anchor_tokens is not None and recent_entity_ids and entity.entity_id not in recent_entity_ids:
                continue
            alias_values = list(dict.fromkeys(aliases_by_entity.get(entity.entity_id, [])))
            alias_text = "、".join(alias_values[:_MAX_ALIASES_PER_ANCHOR_ENTITY])
            seen = sorted(set(appearances_by_entity.get(entity.entity_id, [])))
            seen_text = f"出场至第{seen[-1]}章" if seen else f"首次第{entity.first_seen_chapter}章"
            alias_suffix = f"，别名：{alias_text}" if alias_text else ""
            entity_lines.append(
                f"- {entity.canonical_name}（{entity.entity_type}，{seen_text}，"
                f"揭示第{entity.revealed_chapter}章{alias_suffix}）"
            )
            selected_entities.append(entity)
            selected_entity_ids.add(entity.entity_id)
            if max_anchor_tokens is not None:
                selected_alias_ids.update(
                    alias.alias_id
                    for alias in aliases
                    if alias.entity_id == entity.entity_id
                    and alias.alias_text in alias_values[:_MAX_ALIASES_PER_ANCHOR_ENTITY]
                )

        if entity_lines:
            section: list[str] = ["实体锚点："]
            for line in entity_lines:
                if not _append_anchor_line(section, line, max_tokens=max_anchor_tokens):
                    break
            if len(section) > 1 and _append_anchor_line(lines, "\n".join(section), max_tokens=max_anchor_tokens):
                selected_count = len(section) - 1
                selected_entities = selected_entities[:selected_count]
                selected_entity_ids = {row.entity_id for row in selected_entities}
                selected_alias_ids = {
                    alias.alias_id
                    for alias in aliases
                    if alias.entity_id in selected_entity_ids
                    and alias.alias_text in aliases_by_entity.get(alias.entity_id, [])[:_MAX_ALIASES_PER_ANCHOR_ENTITY]
                }
            else:
                selected_entities = []
                selected_entity_ids = set()
                selected_alias_ids = set()

    selected_relationships: list[Any] = []
    if relationships:
        relationship_lines: list[tuple[str, Any]] = []
        for rel in relationships:
            if max_anchor_tokens is not None and recent_entity_ids and (
                rel.source_entity_id not in recent_entity_ids
                and rel.target_entity_id not in recent_entity_ids
            ):
                continue
            source_name = _anchor_entity_name(rel.source_entity_id, entity_names)
            target_name = _anchor_entity_name(rel.target_entity_id, entity_names)
            lore_suffix = f"，已揭示：{rel.lore_text.strip()}" if rel.lore_text else ""
            relationship_lines.append(
                (
                    f"- {source_name} {rel.type} {target_name}（第{rel.start_chapter}章起，"
                    f"揭示第{rel.revealed_chapter}章{lore_suffix}）",
                    rel,
                )
            )
        if relationship_lines:
            section = ["关系锚点："]
            for line, rel in relationship_lines:
                if not _append_anchor_line(section, line, max_tokens=max_anchor_tokens):
                    break
                selected_relationships.append(rel)
            if len(section) > 1 and not _append_anchor_line(lines, "\n".join(section), max_tokens=max_anchor_tokens):
                selected_relationships = []

    if not lines:
        lines.append("无已确认且章节安全的图谱锚点。")

    if max_anchor_tokens is None:
        selected_entities = entities
        selected_alias_ids = {row.alias_id for row in aliases}
        selected_entity_ids = {row.entity_id for row in entities}
        selected_relationships = relationships

    selected_aliases = [row for row in aliases if row.alias_id in selected_alias_ids]
    if max_anchor_tokens is not None and selected_recent_chapters:
        selected_appearances = [
            row
            for row in appearances
            if row.entity_id in selected_entity_ids and row.chapter_number in selected_recent_chapters
        ]
    else:
        selected_appearances = [row for row in appearances if row.entity_id in selected_entity_ids]
    anchor_text = "\n".join(lines)
    audit = _graph_anchor_audit(
        chapter_number=chapter_number,
        entities=selected_entities,
        aliases=selected_aliases,
        appearances=selected_appearances,
        relationships=selected_relationships,
    )
    if max_anchor_tokens is not None:
        raw_anchor_text = _raw_anchor_text_for_audit
        if raw_anchor_text is None:
            raw_anchor_text, _ = build_graph_continuity_anchors(
                graph_client=graph_client,
                chapter_number=chapter_number,
            )
        audit.update(
            {
                "anchor_pruned": audit != raw_audit,
                "anchor_token_count": count_tokens(anchor_text),
                "anchor_token_budget": max_anchor_tokens,
                "raw_anchor_token_count": count_tokens(raw_anchor_text),
                "raw_entity_count": raw_audit["entity_count"],
                "raw_alias_count": raw_audit["alias_count"],
                "raw_appearance_count": raw_audit["appearance_count"],
                "raw_relationship_count": raw_audit["relationship_count"],
            }
        )
    return anchor_text, audit


def _build_raw_graph_continuity_anchors(
    *,
    graph_client: GraphClient,
    chapter_number: int,
) -> tuple[str, dict[str, object]]:
    return build_graph_continuity_anchors(
        graph_client=graph_client,
        chapter_number=chapter_number,
    )


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

    raw_anchors, raw_audit = _build_raw_graph_continuity_anchors(
        graph_client=graph_client,
        chapter_number=chapter_number,
    )
    anchors, audit = build_graph_continuity_anchors(
        graph_client=graph_client,
        chapter_number=chapter_number,
        recent_summary_chapters=[row.chapter_number for row in recent],
        max_anchor_tokens=_GRAPH_CONTINUITY_ANCHOR_MAX_TOKENS,
        _raw_anchor_text_for_audit=raw_anchors,
    )
    audit["base_chapter_number"] = base_chapter
    audit["recent_summary_chapters"] = [row.chapter_number for row in recent]
    source_audit = dict(raw_audit)
    source_audit["base_chapter_number"] = base_chapter
    source_audit["recent_summary_chapters"] = [row.chapter_number for row in recent]
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
        "graph_anchors_zh": raw_anchors,
        "graph_anchor_audit": source_audit,
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
    run_id: str,
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
        try:
            compact, audit = _validate_graph_continuity_output(cached, config=config)
            record_cache_hit(llm_client)
            return compact, audit
        except ValueError as exc:
            logger.info(
                "Ignoring invalid graph continuity cache for chapter {}: {}",
                continuity_input.current_chapter_number,
                exc,
            )

    last_error: ValueError | None = None
    raw_output = ""
    for attempt_number in range(1, _MAX_GRAPH_CONTINUITY_ATTEMPTS + 1):
        raw_output = llm_client.generate_text(model_name=model_name, prompt=rendered).strip()
        try:
            compact, audit = _validate_graph_continuity_output(raw_output, config=config)
            break
        except ValueError as exc:
            last_error = exc
            if attempt_number >= _MAX_GRAPH_CONTINUITY_ATTEMPTS:
                raise
            _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.graph_compact.retry",
                chapter_number=continuity_input.current_chapter_number,
                attempt_number=attempt_number,
                reason=str(exc),
            )
    else:  # pragma: no cover - loop always returns or raises
        if last_error is not None:
            raise last_error
        raise ValueError("graph_continuity_output_invalid: unknown validation failure")

    if cache_root is not None:
        save_cached_text(cache_root, identity, raw_output)
    return compact, audit


def _chunk_refs(chapter_refs: list[Any], chunk_size: int) -> list[list[Any]]:
    if chunk_size <= 0:
        return [chapter_refs]
    return [chapter_refs[index : index + chunk_size] for index in range(0, len(chapter_refs), chunk_size)]


def _chunk_event_payload(
    *,
    chunk_index: int,
    chunk_count: int,
    refs: list[Any],
    chunk_size: int,
    last_good_chapter: int,
) -> dict[str, object]:
    return {
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "chapter_start": refs[0].chapter_number,
        "chapter_end": refs[-1].chapter_number,
        "chunk_size": chunk_size,
        "last_good_chapter": last_good_chapter,
    }


def _artifact_path(paths: Any, chapter_number: int) -> Path:
    return Path(paths.summaries_dir) / f"chapter-{chapter_number}-graph-continuity.json"


def _current_graph_en_record(
    conn: Any,
    *,
    release_id: str,
    chapter_number: int,
    zh_record: ValidatedSummaryZhRecord,
    glossary_hash: str,
) -> Any | None:
    expected_source_hash = hash_validated_summary(zh_record)
    for row in list_derived_summaries(conn, release_id=release_id, chapter_number=chapter_number):
        if (
            row.summary_type == "story_so_far_en_graph_compact"
            and row.source_summary_id == zh_record.summary_id
            and row.source_summary_hash == expected_source_hash
            and row.glossary_version_hash == glossary_hash
        ):
            return row
    return None


def _load_existing_model_anchor_audit(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    audit = payload.get("model_anchor_audit", {})
    return dict(audit) if isinstance(audit, dict) else {}


def _write_graph_continuity_artifact(
    *,
    path: Path,
    release_id: str,
    run_id: str,
    chapter_number: int,
    zh_record: ValidatedSummaryZhRecord,
    en_record: Any,
    continuity_input: GraphContinuityInput,
    model_anchor_audit: dict[str, object],
) -> None:
    _write_json(
        path,
        {
            "release_id": release_id,
            "run_id": run_id,
            "chapter_number": chapter_number,
            "schema_version": 1,
            "validated": {
                "story_so_far_zh_graph_compact": zh_record.to_json_dict(),
            },
            "derived": {
                "story_so_far_en_graph_compact": en_record.to_json_dict(),
            },
            "graph_anchor_audit": continuity_input.graph_anchor_audit,
            "model_anchor_audit": model_anchor_audit,
            "graph_anchors_zh": continuity_input.graph_anchors_zh,
        },
    )


def _completed_chunk_is_resume_skippable(
    conn: Any,
    *,
    checkpoint: Any,
    paths: Any,
    release_id: str,
    refs: list[Any],
    graph_client: GraphClient,
    config: AppConfig,
    glossary_hash: str,
) -> bool:
    if checkpoint.status != "completed":
        return False
    try:
        last_good_chapter = int(checkpoint.metadata.get("last_good_chapter", 0))
    except (TypeError, ValueError):
        return False
    if int(checkpoint.chapter_start) != refs[0].chapter_number:
        return False
    if int(checkpoint.chapter_end) != refs[-1].chapter_number:
        return False
    if last_good_chapter < refs[-1].chapter_number:
        return False

    for ref in refs:
        chapter_number = ref.chapter_number
        if get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_short",
        ) is None:
            continue
        continuity_input = build_graph_continuity_input(
            conn=conn,
            release_id=release_id,
            chapter_number=chapter_number,
            graph_client=graph_client,
            rebase_interval=config.summaries.graph_continuity_rebase_interval,
        )
        zh_record = get_validated_summary(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="story_so_far_zh_graph_compact",
        )
        if zh_record is None or zh_record.derived_from_chapter_hash != continuity_input.source_hash:
            return False
        if (
            _current_graph_en_record(
                conn,
                release_id=release_id,
                chapter_number=chapter_number,
                zh_record=zh_record,
                glossary_hash=glossary_hash,
            )
            is None
        ):
            return False
        if not _artifact_path(paths, chapter_number).exists():
            return False
    return True


def _derive_graph_compact_english(
    *,
    db_path: Path,
    release_id: str,
    run_id: str,
    llm_client: LLMClient,
    model_name: str,
    prompt: PromptTemplate,
    zh_result: _GraphContinuityZhResult,
    locked_glossary: list[Any],
    glossary_hash: str,
    config: AppConfig,
) -> _GraphContinuityEnResult:
    en_text = derive_english_summary(
        llm_client=llm_client,
        model_name=model_name,
        prompt_template=prompt.template,
        source_text_zh=zh_result.record.content_zh,
        locked_glossary=locked_glossary,
        config=config,
        stage_name=f"{_STAGE_NAME}.graph-compact-en",
        chapter_number=zh_result.chapter_number,
    )
    conn = open_connection(db_path)
    ensure_schema(conn, "summaries")
    try:
        en_record = save_derived_summary(
            conn,
            release_id=release_id,
            chapter_number=zh_result.chapter_number,
            summary_type="story_so_far_en_graph_compact",
            content_en=en_text,
            source_summary_id=zh_result.record.summary_id,
            source_summary_hash=hash_validated_summary(zh_result.record),
            glossary_version_hash=glossary_hash,
            model_name=model_name,
            prompt_version=prompt.version,
            run_id=run_id,
        )
    finally:
        conn.close()
    return _GraphContinuityEnResult(
        chapter_number=zh_result.chapter_number,
        record=zh_result.record,
        en_record=en_record,
        artifact_path=zh_result.artifact_path,
    )


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
    resume: bool = True,
    force: bool = False,
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
        effective_chunk_size = (
            config_obj.batch_order.summary_chunk_multiplier
            * config_obj.summaries.chapter_concurrency
        )
        chunked = config_obj.batch_order.enabled and len(chapter_refs) > effective_chunk_size
        chunks = _chunk_refs(chapter_refs, effective_chunk_size) if chunked else [chapter_refs]
        completed_chunk_index = -1
        last_good_chapter = 0

        for chunk_index, chunk_refs in enumerate(chunks):
            if chunked and resume and not force:
                chunk_checkpoint = load_chunk_checkpoint(
                    conn,
                    release_id=release_id,
                    run_id=run_id,
                    stage_name=_STAGE_NAME,
                    chunk_index=chunk_index,
                )
                if chunk_checkpoint is not None and _completed_chunk_is_resume_skippable(
                    conn,
                    checkpoint=chunk_checkpoint,
                    paths=paths,
                    release_id=release_id,
                    refs=chunk_refs,
                    graph_client=graph,
                    config=config_obj,
                    glossary_hash=glossary_hash,
                ):
                    completed_chunk_index = chunk_index
                    last_good_chapter = chunk_refs[-1].chapter_number
                    continue

            if chunked:
                payload = _chunk_event_payload(
                    chunk_index=chunk_index,
                    chunk_count=len(chunks),
                    refs=chunk_refs,
                    chunk_size=effective_chunk_size,
                    last_good_chapter=last_good_chapter,
                )
                _emit(run_id, release_id, f"{_STAGE_NAME}.chunk_started", **payload)
                save_chunk_checkpoint(
                    conn,
                    release_id=release_id,
                    run_id=run_id,
                    stage_name=_STAGE_NAME,
                    chunk_index=chunk_index,
                    chapter_start=chunk_refs[0].chapter_number,
                    chapter_end=chunk_refs[-1].chapter_number,
                    status="running",
                    metadata=payload,
                )

            zh_results: list[_GraphContinuityZhResult] = []
            failed_chapter_number = chunk_refs[0].chapter_number
            try:
                for ref in chunk_refs:
                    chapter_number = ref.chapter_number
                    failed_chapter_number = chapter_number
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
                        last_good_chapter = chapter_number
                        continue

                    _emit(run_id, release_id, f"{_STAGE_NAME}.chapter_started", chapter_number=chapter_number)
                    continuity_input = build_graph_continuity_input(
                        conn=conn,
                        release_id=release_id,
                        chapter_number=chapter_number,
                        graph_client=graph,
                        rebase_interval=config_obj.summaries.graph_continuity_rebase_interval,
                    )
                    if continuity_input.graph_anchor_audit.get("anchor_pruned"):
                        _emit(
                            run_id,
                            release_id,
                            f"{_STAGE_NAME}.graph_anchors_pruned",
                            chapter_number=chapter_number,
                            anchor_token_count=continuity_input.graph_anchor_audit.get("anchor_token_count"),
                            anchor_token_budget=continuity_input.graph_anchor_audit.get("anchor_token_budget"),
                            raw_anchor_token_count=continuity_input.graph_anchor_audit.get("raw_anchor_token_count"),
                            entity_count=continuity_input.graph_anchor_audit.get("entity_count"),
                            raw_entity_count=continuity_input.graph_anchor_audit.get("raw_entity_count"),
                            relationship_count=continuity_input.graph_anchor_audit.get("relationship_count"),
                            raw_relationship_count=continuity_input.graph_anchor_audit.get("raw_relationship_count"),
                        )
                    artifact_path = _artifact_path(paths, chapter_number)
                    existing_record = get_validated_summary(
                        conn,
                        release_id=release_id,
                        chapter_number=chapter_number,
                        summary_type="story_so_far_zh_graph_compact",
                    )
                    can_reuse_zh = (
                        chunked
                        and resume
                        and not force
                        and existing_record is not None
                        and existing_record.derived_from_chapter_hash == continuity_input.source_hash
                    )
                    if can_reuse_zh:
                        assert existing_record is not None
                        record = existing_record
                        model_anchor_audit = _load_existing_model_anchor_audit(artifact_path)
                    else:
                        compact_text, model_anchor_audit = refresh_graph_continuity_text(
                            llm_client=client,
                            release_id=release_id,
                            run_id=run_id,
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
                    zh_results.append(
                        _GraphContinuityZhResult(
                            chapter_number=chapter_number,
                            continuity_input=continuity_input,
                            record=record,
                            model_anchor_audit=model_anchor_audit,
                            artifact_path=artifact_path,
                        )
                    )

                english_jobs: list[_GraphContinuityZhResult] = []
                existing_english: list[tuple[_GraphContinuityZhResult, Any]] = []
                for zh_result in zh_results:
                    en_record = (
                        _current_graph_en_record(
                            conn,
                            release_id=release_id,
                            chapter_number=zh_result.chapter_number,
                            zh_record=zh_result.record,
                            glossary_hash=glossary_hash,
                        )
                        if chunked and resume and not force
                        else None
                    )
                    if en_record is None:
                        english_jobs.append(zh_result)
                    else:
                        existing_english.append((zh_result, en_record))

                completed_english: list[_GraphContinuityEnResult] = []
                if english_jobs:
                    with ThreadPoolExecutor(max_workers=config_obj.summaries.chapter_concurrency) as executor:
                        futures = {
                            executor.submit(
                                _derive_graph_compact_english,
                                db_path=paths.db_path,
                                release_id=release_id,
                                run_id=run_id,
                                llm_client=client,
                                model_name=config_obj.models.translator_name,
                                prompt=prompt_en,
                                zh_result=zh_result,
                                locked_glossary=locked_glossary,
                                glossary_hash=glossary_hash,
                                config=config_obj,
                            ): zh_result
                            for zh_result in english_jobs
                        }
                        for future in as_completed(futures):
                            failed_chapter_number = futures[future].chapter_number
                            completed_english.append(future.result())

                english_by_chapter: dict[int, tuple[_GraphContinuityZhResult, Any]] = {
                    zh_result.chapter_number: (zh_result, en_record)
                    for zh_result, en_record in existing_english
                }
                for en_result in completed_english:
                    source = next(
                        result
                        for result in zh_results
                        if result.chapter_number == en_result.chapter_number
                    )
                    english_by_chapter[en_result.chapter_number] = (source, en_result.en_record)

                for zh_result in sorted(zh_results, key=lambda result: result.chapter_number):
                    en_record = english_by_chapter[zh_result.chapter_number][1]
                    _write_graph_continuity_artifact(
                        path=zh_result.artifact_path,
                        release_id=release_id,
                        run_id=run_id,
                        chapter_number=zh_result.chapter_number,
                        zh_record=zh_result.record,
                        en_record=en_record,
                        continuity_input=zh_result.continuity_input,
                        model_anchor_audit=zh_result.model_anchor_audit,
                    )
                    refreshed.append(
                        {
                            "chapter_number": zh_result.chapter_number,
                            "summary_id": zh_result.record.summary_id,
                            "artifact": str(zh_result.artifact_path),
                            "anchor_count": zh_result.continuity_input.graph_anchor_audit["entity_count"],
                        }
                    )
                    last_good_chapter = zh_result.chapter_number
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.chapter_completed",
                        chapter_number=zh_result.chapter_number,
                        summary_id=zh_result.record.summary_id,
                        artifact_path=str(zh_result.artifact_path),
                    )
                    raise_if_stop_requested(
                        stop_token,
                        checkpoint={"refreshed_chapters": [row["chapter_number"] for row in refreshed]},
                        message=f"Continuity refresh stopped after chapter {zh_result.chapter_number}",
                    )

                if chunked:
                    last_good_chapter = chunk_refs[-1].chapter_number
                    completed_chunk_index = chunk_index
                    payload = _chunk_event_payload(
                        chunk_index=chunk_index,
                        chunk_count=len(chunks),
                        refs=chunk_refs,
                        chunk_size=effective_chunk_size,
                        last_good_chapter=last_good_chapter,
                    )
                    _emit(run_id, release_id, f"{_STAGE_NAME}.chunk_completed", **payload)
                    save_chunk_checkpoint(
                        conn,
                        release_id=release_id,
                        run_id=run_id,
                        stage_name=_STAGE_NAME,
                        chunk_index=chunk_index,
                        chapter_start=chunk_refs[0].chapter_number,
                        chapter_end=chunk_refs[-1].chapter_number,
                        status="completed",
                        metadata=payload,
                    )
            except StopRequested:
                raise
            except Exception as exc:
                if chunked:
                    payload = _chunk_event_payload(
                        chunk_index=chunk_index,
                        chunk_count=len(chunks),
                        refs=chunk_refs,
                        chunk_size=effective_chunk_size,
                        last_good_chapter=last_good_chapter,
                    )
                    _emit(
                        run_id,
                        release_id,
                        f"{_STAGE_NAME}.chunk_failed",
                        severity="error",
                        message=f"Continuity chunk {chunk_index} failed: {exc}",
                        reason=str(exc),
                        **payload,
                    )
                    save_chunk_checkpoint(
                        conn,
                        release_id=release_id,
                        run_id=run_id,
                        stage_name=_STAGE_NAME,
                        chunk_index=chunk_index,
                        chapter_start=chunk_refs[0].chapter_number,
                        chapter_end=chunk_refs[-1].chapter_number,
                        status="failed",
                        metadata={**payload, "reason": str(exc)},
                    )
                _emit(
                    run_id,
                    release_id,
                    f"{_STAGE_NAME}.chapter_failed",
                    chapter_number=failed_chapter_number,
                    severity="error",
                    message=f"Continuity refresh failed for chapter {failed_chapter_number}: {exc}",
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
        "checkpoint": {
            "chunked": chunked,
            "completed_chunk_index": completed_chunk_index,
            "last_good_chapter": last_good_chapter,
        },
        **usage_payload_delta(client, usage_before),
    }
