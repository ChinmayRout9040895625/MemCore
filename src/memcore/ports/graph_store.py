"""GraphStore port — knowledge graph of entities and temporal relations.

Default adapter: Neo4j (ADR-003). Used for entity linking, relationship storage,
and bounded graph expansion during retrieval.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from memcore.domain.models import Entity, Relation


class GraphStore(ABC):
    """Port for a property-graph store."""

    @abstractmethod
    async def upsert_entity(self, entity: Entity) -> None:
        """Insert or update an entity node (by id)."""

    @abstractmethod
    async def upsert_relation(self, relation: Relation) -> None:
        """Insert or update a relation edge (by id)."""

    @abstractmethod
    async def get_entity(self, tenant_id: str, entity_id: str) -> Entity | None:
        """Fetch a single entity, or ``None`` if absent."""

    @abstractmethod
    async def find_entities(
        self, tenant_id: str, agent_id: str, name: str, *, limit: int = 10
    ) -> list[Entity]:
        """Fuzzy/alias lookup used for entity linking during consolidation."""

    @abstractmethod
    async def neighbors(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        max_hops: int = 1,
        limit: int = 50,
    ) -> list[Relation]:
        """Return relations within ``max_hops`` of an entity (bounded)."""

    @abstractmethod
    async def delete_entity(self, tenant_id: str, entity_id: str) -> None:
        """Hard-delete an entity and its incident relations."""
