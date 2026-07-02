"""In-memory :class:`GraphStore`.

A faithful reference: entities keyed by ``(tenant_id, id)``, relations held in a
flat list, BFS neighbour expansion bounded by hops + limit. Tenant isolation is
enforced on every read, mirroring what the Neo4j adapter must guarantee.
"""

from __future__ import annotations

from collections import deque

from memcore.domain.models import Entity, Relation
from memcore.ports.graph_store import GraphStore


class InMemoryGraphStore(GraphStore):
    def __init__(self) -> None:
        self._entities: dict[tuple[str, str], Entity] = {}
        self._relations: dict[str, Relation] = {}

    async def upsert_entity(self, entity: Entity) -> None:
        self._entities[(entity.tenant_id, entity.id)] = entity

    async def upsert_relation(self, relation: Relation) -> None:
        self._relations[relation.id] = relation

    async def get_entity(self, tenant_id: str, entity_id: str) -> Entity | None:
        return self._entities.get((tenant_id, entity_id))

    async def find_entities(
        self, tenant_id: str, agent_id: str, name: str, *, limit: int = 10
    ) -> list[Entity]:
        needle = name.casefold()
        matches = [
            ent
            for (tid, _), ent in self._entities.items()
            if tid == tenant_id
            and ent.agent_id == agent_id
            and (
                needle in ent.name.casefold()
                or needle == ent.canonical_name.casefold()
                or any(needle == alias.casefold() for alias in ent.aliases)
            )
        ]
        matches.sort(key=lambda e: e.name)
        return matches[:limit]

    async def neighbors(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        max_hops: int = 1,
        limit: int = 50,
    ) -> list[Relation]:
        # Adjacency restricted to this tenant's active relations.
        rels = [
            r
            for r in self._relations.values()
            if r.tenant_id == tenant_id and r.status.value == "active"
        ]
        seen_rel: dict[str, Relation] = {}
        frontier: deque[tuple[str, int]] = deque([(entity_id, 0)])
        visited: set[str] = {entity_id}
        while frontier:
            node, hop = frontier.popleft()
            if hop >= max_hops:
                continue
            for r in rels:
                if node in (r.subject_id, r.object_id):
                    seen_rel[r.id] = r
                    other = r.object_id if r.subject_id == node else r.subject_id
                    if other not in visited:
                        visited.add(other)
                        frontier.append((other, hop + 1))
        return list(seen_rel.values())[:limit]

    async def delete_entity(self, tenant_id: str, entity_id: str) -> None:
        self._entities.pop((tenant_id, entity_id), None)
        self._relations = {
            rid: r
            for rid, r in self._relations.items()
            if not (
                r.tenant_id == tenant_id and entity_id in (r.subject_id, r.object_id)
            )
        }
