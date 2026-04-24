from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import importlib
import json
from pathlib import Path
from typing import Any, Protocol

from resemantica.graph.models import (
    GraphAlias,
    GraphAppearance,
    GraphEntity,
    GraphRelationship,
    GraphSnapshotRecord,
)


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class GraphBackend(Protocol):
    def upsert_entities(self, *, entities: list[GraphEntity]) -> None: ...
    def upsert_aliases(self, *, aliases: list[GraphAlias]) -> None: ...
    def upsert_appearances(self, *, appearances: list[GraphAppearance]) -> None: ...
    def upsert_relationships(self, *, relationships: list[GraphRelationship]) -> None: ...
    def list_entities(self, *, status: str | None = None) -> list[GraphEntity]: ...
    def list_aliases(self, *, status: str | None = None) -> list[GraphAlias]: ...
    def list_appearances(self, *, status: str | None = None) -> list[GraphAppearance]: ...
    def list_relationships(self, *, status: str | None = None) -> list[GraphRelationship]: ...


class InMemoryGraphBackend:
    def __init__(self) -> None:
        self._entities: dict[str, GraphEntity] = {}
        self._aliases: dict[str, GraphAlias] = {}
        self._appearances: dict[str, GraphAppearance] = {}
        self._relationships: dict[str, GraphRelationship] = {}

    def upsert_entities(self, *, entities: list[GraphEntity]) -> None:
        for entity in entities:
            self._entities[entity.entity_id] = entity

    def upsert_aliases(self, *, aliases: list[GraphAlias]) -> None:
        for alias in aliases:
            self._aliases[alias.alias_id] = alias

    def upsert_appearances(self, *, appearances: list[GraphAppearance]) -> None:
        for appearance in appearances:
            self._appearances[appearance.appearance_id] = appearance

    def upsert_relationships(self, *, relationships: list[GraphRelationship]) -> None:
        for relationship in relationships:
            self._relationships[relationship.relationship_id] = relationship

    @staticmethod
    def _filter_by_status[T](rows: list[T], *, status: str | None, getter: Any) -> list[T]:
        if status is None:
            return rows
        return [row for row in rows if getter(row) == status]

    def list_entities(self, *, status: str | None = None) -> list[GraphEntity]:
        rows = sorted(self._entities.values(), key=lambda row: row.entity_id)
        return self._filter_by_status(rows, status=status, getter=lambda row: row.status)

    def list_aliases(self, *, status: str | None = None) -> list[GraphAlias]:
        rows = sorted(self._aliases.values(), key=lambda row: row.alias_id)
        return self._filter_by_status(rows, status=status, getter=lambda row: row.status)

    def list_appearances(self, *, status: str | None = None) -> list[GraphAppearance]:
        rows = sorted(
            self._appearances.values(),
            key=lambda row: (row.chapter_number, row.appearance_id),
        )
        return self._filter_by_status(rows, status=status, getter=lambda row: row.status)

    def list_relationships(self, *, status: str | None = None) -> list[GraphRelationship]:
        rows = sorted(self._relationships.values(), key=lambda row: row.relationship_id)
        return self._filter_by_status(rows, status=status, getter=lambda row: row.status)


class LadybugGraphBackend(InMemoryGraphBackend):
    def __init__(self, *, db_path: Path) -> None:
        super().__init__()
        self._db_path = db_path.resolve()
        self._state_path = self._db_path.with_suffix(".state.json")
        self._connection = self._open_ladybug_connection()
        self._load_state_from_disk()

    def _open_ladybug_connection(self) -> Any:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lb = importlib.import_module("ladybug")
        except ImportError as exc:
            raise RuntimeError(
                "ladybug package is required for Graph MVP. Install dependencies before running preprocess graph."
            ) from exc

        try:
            database = lb.Database(str(self._db_path))
            return lb.Connection(database)
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize LadybugDB at {self._db_path}: {exc}") from exc

    def _touch_connection(self) -> None:
        try:
            self._connection.execute("RETURN 1;")
        except Exception:
            # Best-effort touch: graph state persistence is handled by deterministic sidecar snapshots.
            pass

    def _load_state_from_disk(self) -> None:
        if not self._state_path.exists():
            return
        payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        entities = [GraphEntity(**row) for row in payload.get("entities", [])]
        aliases = [GraphAlias(**row) for row in payload.get("aliases", [])]
        appearances = [GraphAppearance(**row) for row in payload.get("appearances", [])]
        relationships = [GraphRelationship(**row) for row in payload.get("relationships", [])]
        super().upsert_entities(entities=entities)
        super().upsert_aliases(aliases=aliases)
        super().upsert_appearances(appearances=appearances)
        super().upsert_relationships(relationships=relationships)

    def _persist_state_to_disk(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "entities": [asdict(row) for row in self.list_entities()],
            "aliases": [asdict(row) for row in self.list_aliases()],
            "appearances": [asdict(row) for row in self.list_appearances()],
            "relationships": [asdict(row) for row in self.list_relationships()],
        }
        self._state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._touch_connection()

    def upsert_entities(self, *, entities: list[GraphEntity]) -> None:
        super().upsert_entities(entities=entities)
        self._persist_state_to_disk()

    def upsert_aliases(self, *, aliases: list[GraphAlias]) -> None:
        super().upsert_aliases(aliases=aliases)
        self._persist_state_to_disk()

    def upsert_appearances(self, *, appearances: list[GraphAppearance]) -> None:
        super().upsert_appearances(appearances=appearances)
        self._persist_state_to_disk()

    def upsert_relationships(self, *, relationships: list[GraphRelationship]) -> None:
        super().upsert_relationships(relationships=relationships)
        self._persist_state_to_disk()


@dataclass(slots=True)
class GraphClient:
    backend: GraphBackend

    @classmethod
    def from_ladybug(cls, *, db_path: Path) -> GraphClient:
        return cls(backend=LadybugGraphBackend(db_path=db_path))

    def upsert_entities(self, *, entities: list[GraphEntity]) -> None:
        self.backend.upsert_entities(entities=entities)

    def upsert_aliases(self, *, aliases: list[GraphAlias]) -> None:
        self.backend.upsert_aliases(aliases=aliases)

    def upsert_appearances(self, *, appearances: list[GraphAppearance]) -> None:
        self.backend.upsert_appearances(appearances=appearances)

    def upsert_relationships(self, *, relationships: list[GraphRelationship]) -> None:
        self.backend.upsert_relationships(relationships=relationships)

    def list_entities(self, *, status: str | None = None) -> list[GraphEntity]:
        return self.backend.list_entities(status=status)

    def list_aliases(self, *, status: str | None = None) -> list[GraphAlias]:
        return self.backend.list_aliases(status=status)

    def list_appearances(self, *, status: str | None = None) -> list[GraphAppearance]:
        return self.backend.list_appearances(status=status)

    def list_relationships(self, *, status: str | None = None) -> list[GraphRelationship]:
        return self.backend.list_relationships(status=status)

    def export_snapshot(
        self,
        *,
        release_id: str,
        graph_db_path: Path,
    ) -> GraphSnapshotRecord:
        entities = [row.to_json_dict() for row in self.list_entities(status="confirmed")]
        aliases = [row.to_json_dict() for row in self.list_aliases(status="confirmed")]
        appearances = [row.to_json_dict() for row in self.list_appearances(status="confirmed")]
        relationships = [row.to_json_dict() for row in self.list_relationships(status="confirmed")]
        payload = {
            "release_id": release_id,
            "entities": entities,
            "aliases": aliases,
            "appearances": appearances,
            "relationships": relationships,
        }
        snapshot_hash = sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return GraphSnapshotRecord(
            snapshot_id=f"gsnp_{snapshot_hash[:24]}",
            release_id=release_id,
            snapshot_hash=snapshot_hash,
            graph_db_path=str(graph_db_path),
            entity_count=len(entities),
            alias_count=len(aliases),
            appearance_count=len(appearances),
            relationship_count=len(relationships),
            schema_version=1,
        )
