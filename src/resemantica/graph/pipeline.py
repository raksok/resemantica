from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from resemantica.chapters.manifest import list_extracted_chapters
from resemantica.db.graph_repo import (
    ensure_graph_schema,
    list_deferred_entities,
    mark_deferred_graph_created,
    mark_deferred_promoted,
    save_graph_snapshot,
    upsert_deferred_entities,
)
from resemantica.db.sqlite import open_connection
from resemantica.db.summary_repo import ensure_summary_schema
from resemantica.graph.client import GraphClient
from resemantica.graph.extractor import extract_entities
from resemantica.graph.models import GraphAppearance, GraphEntity
from resemantica.graph.validators import validate_graph_state
from resemantica.db.glossary_repo import ensure_glossary_schema, find_exact_locked_entry, list_locked_entries
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import load_prompt
from resemantica.orchestration.events import emit_event
from resemantica.settings import AppConfig, derive_paths, load_config

_STAGE_NAME = "preprocess-graph"


def _chapter_number_from_path(path: Path) -> int:
    return int(path.stem.split("-", 1)[1])


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _build_graph_client(paths: Any, graph_client: GraphClient | None) -> GraphClient:
    if graph_client is not None:
        return graph_client
    return GraphClient.from_ladybug(db_path=paths.graph_db_path)


def _entity_id(*, release_id: str, category: str, normalized_source: str) -> str:
    digest = sha256(f"{release_id}:{category}:{normalized_source}".encode("utf-8")).hexdigest()[:24]
    return f"ent_{digest}"


def _appearance_id(*, release_id: str, entity_id: str, chapter_number: int) -> str:
    digest = sha256(f"{release_id}:{entity_id}:{chapter_number}".encode("utf-8")).hexdigest()[:24]
    return f"app_{digest}"


def _merge_entities(entities: list[GraphEntity]) -> list[GraphEntity]:
    by_id: dict[str, GraphEntity] = {}
    for entity in entities:
        current = by_id.get(entity.entity_id)
        if current is None:
            by_id[entity.entity_id] = entity
            continue
        current.first_seen_chapter = min(current.first_seen_chapter, entity.first_seen_chapter)
        current.last_seen_chapter = max(current.last_seen_chapter, entity.last_seen_chapter)
        current.revealed_chapter = min(current.revealed_chapter, entity.revealed_chapter)
        if entity.glossary_entry_id and not current.glossary_entry_id:
            current.glossary_entry_id = entity.glossary_entry_id
            current.canonical_name = entity.canonical_name
    return sorted(by_id.values(), key=lambda row: row.entity_id)


def _merge_appearances(appearances: list[GraphAppearance]) -> list[GraphAppearance]:
    by_id: dict[str, GraphAppearance] = {}
    for appearance in appearances:
        by_id[appearance.appearance_id] = appearance
    return sorted(by_id.values(), key=lambda row: (row.chapter_number, row.appearance_id))


def _build_llm_client(config: AppConfig, llm_client: LLMClient | None) -> LLMClient:
    if llm_client is not None:
        return llm_client
    return LLMClient(
        base_url=config.llm.base_url,
        timeout_seconds=config.llm.timeout_seconds,
        max_retries=config.llm.max_retries,
    )


def _filtered_chapter_count(
    extracted_chapters_dir: Path,
    *,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
) -> int:
    chapter_files = sorted(
        extracted_chapters_dir.glob("chapter-*.json"),
        key=_chapter_number_from_path,
    )
    return len(
        [
            path
            for path in chapter_files
            if (chapter_start is None or _chapter_number_from_path(path) >= chapter_start)
            and (chapter_end is None or _chapter_number_from_path(path) <= chapter_end)
        ]
    )


def _emit(run_id: str, release_id: str, event_type: str, **kwargs: object) -> None:
    chapter_number = kwargs.pop("chapter_number", None)
    message = str(kwargs.pop("message", ""))
    severity = str(kwargs.pop("severity", "info"))
    try:
        emit_event(
            run_id,
            release_id,
            event_type,
            _STAGE_NAME,
            chapter_number=chapter_number if isinstance(chapter_number, int) else None,
            severity=severity,
            message=message,
            payload=dict(kwargs),
        )
    except Exception:
        pass


def preprocess_graph(
    *,
    release_id: str,
    run_id: str = "graph",
    config: AppConfig | None = None,
    project_root: Path | None = None,
    graph_client: GraphClient | None = None,
    llm_client: LLMClient | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
) -> dict[str, Any]:
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    chapter_refs = list_extracted_chapters(
        paths,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
    )
    graph = _build_graph_client(paths, graph_client)

    prompt = load_prompt("graph_extract.txt")
    llm_client_internal = _build_llm_client(config_obj, llm_client)

    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    ensure_graph_schema(conn)
    ensure_summary_schema(conn)

    warnings: list[str] = []

    try:
        _emit(
            run_id,
            release_id,
            f"{_STAGE_NAME}.started",
            total_chapters=len(chapter_refs),
        )
        locked_glossary = list_locked_entries(conn, release_id=release_id)

        skip_chapters: set[int] = set()
        cursor = conn.execute(
            "SELECT chapter_number FROM summary_drafts WHERE release_id = ? AND summary_type = 'chapter_summary_zh_structured' AND is_story_chapter = 0",
            (release_id,),
        )
        for row in cursor.fetchall():
            skip_chapters.add(int(row[0]))

        extraction = extract_entities(
            release_id=release_id,
            extracted_chapters_dir=paths.extracted_chapters_dir,
            locked_glossary=locked_glossary,
            llm_client=llm_client_internal,
            model_name=config_obj.models.analyst_name,
            prompt_template=prompt.template,
            prompt_version=prompt.version,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
            skip_chapters=skip_chapters or None,
            config=config_obj,
            chapter_refs=chapter_refs,
            cache_root=paths.release_root / "cache" / "llm",
            event_callback=lambda event_name, chapter_number, payload: _emit(
                run_id,
                release_id,
                f"{_STAGE_NAME}.{event_name}",
                chapter_number=chapter_number,
                **payload,
            ),
        )
        warnings.extend(extraction.warnings)

        upsert_deferred_entities(conn, deferred_entities=extraction.deferred_entities)

        resolved_entities: list[GraphEntity] = []
        resolved_appearances: list[GraphAppearance] = []
        pending_deferred = list_deferred_entities(
            conn,
            release_id=release_id,
            status="pending_glossary",
        )
        for deferred in pending_deferred:
            locked_entry = find_exact_locked_entry(
                conn,
                release_id=release_id,
                normalized_source_term=deferred.normalized_term_text,
                category=deferred.category,
            )
            if locked_entry is None:
                continue

            mark_deferred_promoted(
                conn,
                deferred_id=deferred.deferred_id,
                glossary_entry_id=locked_entry.glossary_entry_id,
            )
            resolved_entity_id = _entity_id(
                release_id=release_id,
                category=locked_entry.category,
                normalized_source=locked_entry.normalized_source_term,
            )
            resolved_entities.append(
                GraphEntity(
                    entity_id=resolved_entity_id,
                    release_id=release_id,
                    entity_type=locked_entry.category,
                    canonical_name=locked_entry.target_term,
                    glossary_entry_id=locked_entry.glossary_entry_id,
                    first_seen_chapter=deferred.source_chapter,
                    last_seen_chapter=deferred.last_seen_chapter,
                    revealed_chapter=deferred.source_chapter,
                    status="provisional",
                    schema_version=1,
                )
            )
            resolved_appearances.append(
                GraphAppearance(
                    appearance_id=_appearance_id(
                        release_id=release_id,
                        entity_id=resolved_entity_id,
                        chapter_number=deferred.source_chapter,
                    ),
                    release_id=release_id,
                    entity_id=resolved_entity_id,
                    chapter_number=deferred.source_chapter,
                    evidence_snippet=deferred.evidence_snippet,
                    status="provisional",
                    schema_version=1,
                )
            )
            mark_deferred_graph_created(conn, deferred_id=deferred.deferred_id)

        provisional_entities = _merge_entities(
            extraction.provisional_entities + resolved_entities
        )
        provisional_aliases = extraction.provisional_aliases
        provisional_appearances = _merge_appearances(
            extraction.provisional_appearances + resolved_appearances
        )
        provisional_relationships = extraction.provisional_relationships

        validation = validate_graph_state(
            entities=provisional_entities,
            aliases=provisional_aliases,
            appearances=provisional_appearances,
            relationships=provisional_relationships,
        )
        if not validation.is_valid:
            raise RuntimeError("graph_validation_failed: " + " | ".join(validation.errors))

        confirmed_entities = [replace(row, status="confirmed") for row in provisional_entities]
        confirmed_aliases = [replace(row, status="confirmed") for row in provisional_aliases]
        confirmed_appearances = [replace(row, status="confirmed") for row in provisional_appearances]
        confirmed_relationships = [replace(row, status="confirmed") for row in provisional_relationships]

        graph.upsert_entities(entities=confirmed_entities)
        graph.upsert_aliases(aliases=confirmed_aliases)
        graph.upsert_appearances(appearances=confirmed_appearances)
        graph.upsert_relationships(relationships=confirmed_relationships)

        snapshot = graph.export_snapshot(
            release_id=release_id,
            graph_db_path=paths.graph_db_path,
        )
        save_graph_snapshot(conn, snapshot=snapshot)

        pending_after = list_deferred_entities(
            conn,
            release_id=release_id,
            status="pending_glossary",
        )
        graph_created_after = list_deferred_entities(
            conn,
            release_id=release_id,
            status="graph_created",
        )

        _write_json(
            paths.graph_snapshot_path,
            {
                "release_id": release_id,
                "run_id": run_id,
                "schema_version": 1,
                "snapshot": snapshot.to_json_dict(),
                "validator_status": validation.status,
            },
        )
        _write_json(
            paths.graph_warnings_path,
            {
                "release_id": release_id,
                "run_id": run_id,
                "schema_version": 1,
                "warnings": warnings,
            },
        )
    finally:
        conn.close()

    _emit(
        run_id,
        release_id,
        f"{_STAGE_NAME}.completed",
        extracted=len(provisional_entities),
        skipped=max(
            0,
            len(chapter_refs) - len({appearance.chapter_number for appearance in provisional_appearances}),
        ),
    )
    return {
        "status": "success",
        "release_id": release_id,
        "run_id": run_id,
        "provisional_entities": len(provisional_entities),
        "confirmed_entities": len(confirmed_entities),
        "deferred_pending_count": len(pending_after),
        "deferred_graph_created_count": len(graph_created_after),
        "snapshot_hash": snapshot.snapshot_hash,
        "snapshot_artifact": str(paths.graph_snapshot_path),
        "warnings_artifact": str(paths.graph_warnings_path),
    }
