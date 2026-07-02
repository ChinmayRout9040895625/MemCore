"""Neo4j-backed :class:`GraphStore`.

Mapping (ADR-0011):
* Entities are ``(:Entity {id, tenant_id, agent_id, ...})`` nodes.
* Relations are a single ``[:REL {id, predicate, tenant_id, ...}]`` edge type,
  which keeps neighbour expansion queries uniform. The semantic predicate lives
  in a property, not the Neo4j relationship type.
* Complex fields are serialized: enums to their value, ``metadata`` to a JSON
  string, datetimes to ISO-8601. Lists of scalars use native Neo4j arrays.
* Every read is filtered by ``tenant_id`` for isolation.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from neo4j import AsyncGraphDatabase, Record

from memcore.domain.enums import EntityType, MemoryStatus
from memcore.domain.models import Entity, Relation
from memcore.exceptions import StorageError
from memcore.ports.graph_store import GraphStore


def _entity_to_props(e: Entity) -> dict[str, Any]:
    return {
        "id": e.id,
        "tenant_id": e.tenant_id,
        "agent_id": e.agent_id,
        "name": e.name,
        "canonical_name": e.canonical_name,
        "type": e.type.value,
        "aliases": list(e.aliases),
        "confidence": e.confidence,
        "first_seen": e.first_seen.isoformat(),
        "last_seen": e.last_seen.isoformat(),
        "source_refs": list(e.source_refs),
        "metadata": json.dumps(e.metadata),
    }


def _entity_from_props(p: dict[str, Any]) -> Entity:
    return Entity(
        id=p["id"],
        tenant_id=p["tenant_id"],
        agent_id=p["agent_id"],
        name=p["name"],
        canonical_name=p["canonical_name"],
        type=EntityType(p["type"]),
        aliases=list(p.get("aliases", [])),
        confidence=p["confidence"],
        first_seen=datetime.fromisoformat(p["first_seen"]),
        last_seen=datetime.fromisoformat(p["last_seen"]),
        source_refs=list(p.get("source_refs", [])),
        metadata=json.loads(p.get("metadata", "{}")),
    )


def _relation_to_props(r: Relation) -> dict[str, Any]:
    return {
        "id": r.id,
        "tenant_id": r.tenant_id,
        "agent_id": r.agent_id,
        "subject_id": r.subject_id,
        "predicate": r.predicate,
        "object_id": r.object_id,
        "confidence": r.confidence,
        "valid_from": r.valid_from.isoformat(),
        "valid_to": r.valid_to.isoformat() if r.valid_to else None,
        "version": r.version,
        "status": r.status.value,
        "provenance": list(r.provenance),
        "metadata": json.dumps(r.metadata),
    }


def _relation_from_props(p: dict[str, Any]) -> Relation:
    return Relation(
        id=p["id"],
        tenant_id=p["tenant_id"],
        agent_id=p["agent_id"],
        subject_id=p["subject_id"],
        predicate=p["predicate"],
        object_id=p["object_id"],
        confidence=p["confidence"],
        valid_from=datetime.fromisoformat(p["valid_from"]),
        valid_to=datetime.fromisoformat(p["valid_to"]) if p.get("valid_to") else None,
        version=p["version"],
        status=MemoryStatus(p["status"]),
        provenance=list(p.get("provenance", [])),
        metadata=json.loads(p.get("metadata", "{}")),
    )


class Neo4jGraphStore(GraphStore):
    def __init__(self, url: str, user: str, password: str) -> None:
        self._driver = AsyncGraphDatabase.driver(url, auth=(user, password))

    async def upsert_entity(self, entity: Entity) -> None:
        query = "MERGE (e:Entity {id: $id}) SET e += $props"
        await self._write(query, {"id": entity.id, "props": _entity_to_props(entity)})

    async def upsert_relation(self, relation: Relation) -> None:
        query = (
            "MERGE (s:Entity {id: $subject_id}) "
            "MERGE (o:Entity {id: $object_id}) "
            "MERGE (s)-[r:REL {id: $id}]->(o) SET r += $props"
        )
        await self._write(
            query,
            {
                "subject_id": relation.subject_id,
                "object_id": relation.object_id,
                "id": relation.id,
                "props": _relation_to_props(relation),
            },
        )

    async def get_entity(self, tenant_id: str, entity_id: str) -> Entity | None:
        query = "MATCH (e:Entity {id: $id, tenant_id: $t}) RETURN e"
        rows = await self._read(query, {"id": entity_id, "t": tenant_id})
        if not rows:
            return None
        return _entity_from_props(dict(rows[0]["e"]))

    async def find_entities(
        self, tenant_id: str, agent_id: str, name: str, *, limit: int = 10
    ) -> list[Entity]:
        query = (
            "MATCH (e:Entity) "
            "WHERE e.tenant_id = $t AND e.agent_id = $a AND ("
            "  toLower(e.name) CONTAINS toLower($name) "
            "  OR toLower(e.canonical_name) = toLower($name) "
            "  OR any(x IN e.aliases WHERE toLower(x) = toLower($name))) "
            "RETURN e ORDER BY e.name LIMIT $limit"
        )
        rows = await self._read(
            query, {"t": tenant_id, "a": agent_id, "name": name, "limit": limit}
        )
        return [_entity_from_props(dict(row["e"])) for row in rows]

    async def neighbors(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        max_hops: int = 1,
        limit: int = 50,
    ) -> list[Relation]:
        hops = max(1, int(max_hops))  # interpolated: bounded, integer-validated
        query = (
            f"MATCH (start:Entity {{id: $id, tenant_id: $t}})-[r:REL*1..{hops}]-(:Entity) "
            "WHERE all(rel IN r WHERE rel.tenant_id = $t AND rel.status = 'active') "
            "UNWIND r AS rel RETURN DISTINCT rel LIMIT $limit"
        )
        rows = await self._read(query, {"id": entity_id, "t": tenant_id, "limit": limit})
        return [_relation_from_props(dict(row["rel"])) for row in rows]

    async def delete_entity(self, tenant_id: str, entity_id: str) -> None:
        query = "MATCH (e:Entity {id: $id, tenant_id: $t}) DETACH DELETE e"
        await self._write(query, {"id": entity_id, "t": tenant_id})

    # -- driver helpers ------------------------------------------------------
    async def _write(self, query: str, params: dict[str, Any]) -> None:
        try:
            async with self._driver.session() as session:
                await (await session.run(query, params)).consume()
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"neo4j write failed: {exc}") from exc

    async def _read(self, query: str, params: dict[str, Any]) -> list[Record]:
        try:
            async with self._driver.session() as session:
                result = await session.run(query, params)
                return [record async for record in result]
        except Exception as exc:  # pragma: no cover - network path
            raise StorageError(f"neo4j read failed: {exc}") from exc

    async def close(self) -> None:
        await self._driver.close()
