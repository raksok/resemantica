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
    def get_chapter_safe_subgraph(self, *, chapter_number: int, include_provisional: bool = False) -> dict[str, list[Any]]: ...


_LADYBUG_CONNECTIONS: dict[Path, Any] = {}


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

    def get_chapter_safe_subgraph(
        self,
        *,
        chapter_number: int,
        include_provisional: bool = False,
    ) -> dict[str, list[Any]]:
        statuses = {"confirmed", "provisional"} if include_provisional else {"confirmed"}
        entities = [
            row
            for row in self.list_entities()
            if row.status in statuses and row.revealed_chapter <= chapter_number
        ]
        entity_ids = {row.entity_id for row in entities}
        aliases = [
            row
            for row in self.list_aliases()
            if row.status in statuses
            and row.entity_id in entity_ids
            and row.revealed_chapter <= chapter_number
            and row.first_seen_chapter <= chapter_number
        ]
        appearances = [
            row
            for row in self.list_appearances()
            if row.status in statuses
            and row.entity_id in entity_ids
            and row.chapter_number <= chapter_number
        ]
        relationships = [
            row
            for row in self.list_relationships()
            if row.status in statuses
            and row.source_entity_id in entity_ids
            and row.target_entity_id in entity_ids
            and row.revealed_chapter <= chapter_number
            and row.start_chapter <= chapter_number
            and (row.end_chapter is None or row.end_chapter >= chapter_number)
        ]
        return {
            "entities": entities,
            "aliases": aliases,
            "appearances": appearances,
            "relationships": relationships,
        }


class LadybugGraphBackend(InMemoryGraphBackend):
    def __init__(self, *, db_path: Path) -> None:
        self._db_path = db_path.resolve()
        self._connection = self._open_ladybug_connection()
        self._ensure_schema()

    def _open_ladybug_connection(self) -> Any:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lb = importlib.import_module("ladybug")
        except ImportError as exc:
            raise RuntimeError(
                "ladybug package is required for Graph MVP. Install dependencies before running preprocess graph."
            ) from exc

        try:
            cached = _LADYBUG_CONNECTIONS.get(self._db_path)
            if cached is not None:
                return cached
            database = lb.Database(str(self._db_path))
            connection = lb.Connection(database)
            _LADYBUG_CONNECTIONS[self._db_path] = connection
            return connection
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize LadybugDB at {self._db_path}: {exc}") from exc

    def _ensure_schema(self) -> None:
        self._connection.execute(
            """
            CREATE NODE TABLE IF NOT EXISTS GraphEntity(
                entity_id STRING,
                status STRING,
                revealed_chapter INT64,
                first_seen_chapter INT64,
                payload STRING,
                PRIMARY KEY(entity_id)
            );
            """
        )
        self._connection.execute(
            """
            CREATE NODE TABLE IF NOT EXISTS GraphAlias(
                alias_id STRING,
                status STRING,
                entity_id STRING,
                revealed_chapter INT64,
                first_seen_chapter INT64,
                payload STRING,
                PRIMARY KEY(alias_id)
            );
            """
        )
        self._connection.execute(
            """
            CREATE NODE TABLE IF NOT EXISTS GraphAppearance(
                appearance_id STRING,
                status STRING,
                entity_id STRING,
                chapter_number INT64,
                payload STRING,
                PRIMARY KEY(appearance_id)
            );
            """
        )
        self._connection.execute(
            """
            CREATE NODE TABLE IF NOT EXISTS GraphRelationship(
                relationship_id STRING,
                status STRING,
                source_entity_id STRING,
                target_entity_id STRING,
                revealed_chapter INT64,
                start_chapter INT64,
                end_chapter INT64,
                payload STRING,
                PRIMARY KEY(relationship_id)
            );
            """
        )

    @staticmethod
    def _cypher_literal(value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return json.dumps(str(value), ensure_ascii=False)

    def _upsert_node(self, *, table: str, key: str, key_value: str, fields: dict[str, Any]) -> None:
        self._connection.execute(
            f"MATCH (n:{table} {{{key}: $key_value}}) DELETE n;",
            {"key_value": key_value},
        )
        properties = ", ".join(
            f"{name}: {self._cypher_literal(value)}" for name, value in fields.items()
        )
        self._connection.execute(
            f"CREATE (:{table} {{{properties}}});",
        )

    def _list_payloads(self, *, table: str, status: str | None) -> list[dict[str, Any]]:
        if status is None:
            rows = self._connection.execute(f"MATCH (n:{table}) RETURN n.payload ORDER BY n.payload;").get_all()
        else:
            rows = self._connection.execute(
                f"MATCH (n:{table}) WHERE n.status = $status RETURN n.payload ORDER BY n.payload;",
                {"status": status},
            ).get_all()
        return [json.loads(row[0]) for row in rows]

    def upsert_entities(self, *, entities: list[GraphEntity]) -> None:
        for entity in entities:
            self._upsert_node(
                table="GraphEntity",
                key="entity_id",
                key_value=entity.entity_id,
                fields={
                    "entity_id": entity.entity_id,
                    "status": entity.status,
                    "revealed_chapter": entity.revealed_chapter,
                    "first_seen_chapter": entity.first_seen_chapter,
                    "payload": _canonical_json(asdict(entity)),
                },
            )

    def upsert_aliases(self, *, aliases: list[GraphAlias]) -> None:
        for alias in aliases:
            self._upsert_node(
                table="GraphAlias",
                key="alias_id",
                key_value=alias.alias_id,
                fields={
                    "alias_id": alias.alias_id,
                    "status": alias.status,
                    "entity_id": alias.entity_id,
                    "revealed_chapter": alias.revealed_chapter,
                    "first_seen_chapter": alias.first_seen_chapter,
                    "payload": _canonical_json(asdict(alias)),
                },
            )

    def upsert_appearances(self, *, appearances: list[GraphAppearance]) -> None:
        for appearance in appearances:
            self._upsert_node(
                table="GraphAppearance",
                key="appearance_id",
                key_value=appearance.appearance_id,
                fields={
                    "appearance_id": appearance.appearance_id,
                    "status": appearance.status,
                    "entity_id": appearance.entity_id,
                    "chapter_number": appearance.chapter_number,
                    "payload": _canonical_json(asdict(appearance)),
                },
            )

    def upsert_relationships(self, *, relationships: list[GraphRelationship]) -> None:
        for relationship in relationships:
            self._upsert_node(
                table="GraphRelationship",
                key="relationship_id",
                key_value=relationship.relationship_id,
                fields={
                    "relationship_id": relationship.relationship_id,
                    "status": relationship.status,
                    "source_entity_id": relationship.source_entity_id,
                    "target_entity_id": relationship.target_entity_id,
                    "revealed_chapter": relationship.revealed_chapter,
                    "start_chapter": relationship.start_chapter,
                    "end_chapter": relationship.end_chapter,
                    "payload": _canonical_json(asdict(relationship)),
                },
            )

    def list_entities(self, *, status: str | None = None) -> list[GraphEntity]:
        return [GraphEntity(**row) for row in self._list_payloads(table="GraphEntity", status=status)]

    def list_aliases(self, *, status: str | None = None) -> list[GraphAlias]:
        return [GraphAlias(**row) for row in self._list_payloads(table="GraphAlias", status=status)]

    def list_appearances(self, *, status: str | None = None) -> list[GraphAppearance]:
        rows = [GraphAppearance(**row) for row in self._list_payloads(table="GraphAppearance", status=status)]
        return sorted(rows, key=lambda row: (row.chapter_number, row.appearance_id))

    def list_relationships(self, *, status: str | None = None) -> list[GraphRelationship]:
        rows = [GraphRelationship(**row) for row in self._list_payloads(table="GraphRelationship", status=status)]
        return sorted(rows, key=lambda row: row.relationship_id)


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

    def get_chapter_safe_subgraph(
        self,
        *,
        chapter_number: int,
        include_provisional: bool = False,
    ) -> dict[str, list[Any]]:
        if chapter_number < 1:
            raise ValueError("chapter_number must be >= 1")
        return self.backend.get_chapter_safe_subgraph(
            chapter_number=chapter_number,
            include_provisional=include_provisional,
        )

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
