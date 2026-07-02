"""Behavioural contract checks for the storage ports.

These are deliberately backend-agnostic: they receive an already-constructed
store, drive it through its public interface, and assert the guarantees the port
promises. They must pass identically for the in-memory reference adapters and
the production Qdrant/Neo4j/Redis adapters.

Collections/keyspaces are namespaced with a random suffix so checks are safe to
run against a shared live backend without cross-test interference.
"""

from __future__ import annotations

from memcore.domain.enums import AuditAction, EntityType, MemoryStatus, MemoryType
from memcore.domain.models import (
    AuditEvent,
    Entity,
    Interaction,
    MemoryRecord,
    Relation,
    Session,
    new_id,
    utcnow,
)
from memcore.exceptions import ConflictError, NotFoundError
from memcore.ports.graph_store import GraphStore
from memcore.ports.memory_store import MemoryStore
from memcore.ports.object_store import ObjectStore
from memcore.ports.vector_store import VectorHit, VectorRecord, VectorStore
from memcore.ports.working_memory import WorkingMemory


async def check_vector_store_contract(store: VectorStore) -> None:
    """Verify upsert, ranked search, tenant filtering, delete and count."""
    collection = f"contract_{new_id().replace('-', '')[:12]}"
    # Point ids are UUIDs: MemCore's real ids, and required by Qdrant.
    a, b, c = new_id(), new_id(), new_id()
    await store.ensure_collection(collection, dimension=3)
    await store.ensure_collection(collection, dimension=3)  # idempotent

    await store.upsert(
        collection,
        [
            VectorRecord(a, [1.0, 0.0, 0.0], {"tenant_id": "t1", "type": "semantic"}),
            VectorRecord(b, [0.0, 1.0, 0.0], {"tenant_id": "t1", "type": "semantic"}),
            VectorRecord(c, [1.0, 0.0, 0.0], {"tenant_id": "t2", "type": "semantic"}),
        ],
    )

    # Ranked by similarity, tenant-filtered: 'c' (t2) must not appear.
    hits: list[VectorHit] = await store.search(
        collection, [0.9, 0.1, 0.0], limit=10, filters={"tenant_id": "t1"}
    )
    ids = [h.id for h in hits]
    assert ids == [a, b], ids
    assert hits[0].score >= hits[1].score
    assert c not in ids  # cross-tenant isolation

    # List-valued filter behaves as membership.
    hits2 = await store.search(
        collection, [1.0, 0.0, 0.0], limit=10, filters={"type": ["semantic", "episodic"]}
    )
    assert {h.id for h in hits2} == {a, b, c}

    # Upsert replaces by id.
    await store.upsert(collection, [VectorRecord(a, [0.0, 0.0, 1.0], {"tenant_id": "t1"})])
    assert await store.count(collection, {"tenant_id": "t1"}) == 2

    await store.delete(collection, [a, b])
    assert await store.count(collection, {"tenant_id": "t1"}) == 0


async def check_working_memory_contract(store: WorkingMemory) -> None:
    """Verify append/recent ordering, scratch KV and clear isolation."""
    session = f"sess_{new_id()[:8]}"

    def turn(i: int) -> Interaction:
        return Interaction(
            tenant_id="t1", agent_id="a1", session_id=session, role="user",
            content=f"turn {i}",
        )

    for i in range(3):
        await store.append(session, turn(i))

    recent = await store.recent(session, limit=10)
    assert [x.content for x in recent] == ["turn 0", "turn 1", "turn 2"]  # oldest-first
    assert (await store.recent(session, limit=1))[0].content == "turn 2"

    await store.set_scratch(session, "theme", "dark")
    assert await store.get_scratch(session, "theme") == "dark"
    assert await store.get_scratch(session, "missing") is None

    await store.clear(session)
    assert await store.recent(session) == []
    assert await store.get_scratch(session, "theme") is None


async def check_object_store_contract(store: ObjectStore) -> None:
    """Verify put/get/list/delete round-trip."""
    prefix = f"contract/{new_id()[:8]}/"
    await store.put(f"{prefix}a.json", b"alpha")
    await store.put(f"{prefix}b.json", b"beta")

    assert await store.get(f"{prefix}a.json") == b"alpha"
    assert await store.get(f"{prefix}missing") is None
    assert await store.list_keys(prefix) == [f"{prefix}a.json", f"{prefix}b.json"]

    await store.delete(f"{prefix}a.json")
    assert await store.get(f"{prefix}a.json") is None
    await store.delete(f"{prefix}a.json")  # idempotent, no raise


async def check_graph_store_contract(store: GraphStore) -> None:
    """Verify entity upsert/lookup, aliasing, bounded neighbours, isolation."""
    alice = Entity(
        tenant_id="t1", agent_id="a1", name="Alice", canonical_name="alice",
        type=EntityType.PERSON, aliases=["Ally"],
    )
    bob = Entity(
        tenant_id="t1", agent_id="a1", name="Bob", canonical_name="bob",
        type=EntityType.PERSON,
    )
    carol = Entity(
        tenant_id="t1", agent_id="a1", name="Carol", canonical_name="carol",
        type=EntityType.PERSON,
    )
    # Same-named entity in another tenant must stay invisible to t1.
    alice_t2 = Entity(
        tenant_id="t2", agent_id="a1", name="Alice", canonical_name="alice",
        type=EntityType.PERSON,
    )
    for ent in (alice, bob, carol, alice_t2):
        await store.upsert_entity(ent)

    fetched = await store.get_entity("t1", alice.id)
    assert fetched is not None and fetched.name == "Alice"
    assert await store.get_entity("t1", alice_t2.id) is None  # wrong tenant

    by_alias = await store.find_entities("t1", "a1", "Ally")
    assert [e.id for e in by_alias] == [alice.id]
    found_alice = await store.find_entities("t1", "a1", "Alice")
    assert {e.id for e in found_alice} == {alice.id}  # not the t2 Alice

    # alice -> bob -> carol ; neighbour expansion is hop-bounded.
    await store.upsert_relation(
        Relation(tenant_id="t1", agent_id="a1", subject_id=alice.id,
                 predicate="knows", object_id=bob.id)
    )
    await store.upsert_relation(
        Relation(tenant_id="t1", agent_id="a1", subject_id=bob.id,
                 predicate="knows", object_id=carol.id)
    )

    one_hop = await store.neighbors("t1", alice.id, max_hops=1)
    assert {r.object_id for r in one_hop} == {bob.id}
    two_hop = await store.neighbors("t1", alice.id, max_hops=2)
    assert {r.object_id for r in two_hop} == {bob.id, carol.id}

    await store.delete_entity("t1", bob.id)
    assert await store.get_entity("t1", bob.id) is None
    # Relations incident to bob are gone.
    assert await store.neighbors("t1", alice.id, max_hops=2) == []


async def check_memory_store_contract(store: MemoryStore) -> None:
    """Verify versioning, isolation, listing, reinforcement, audit, sessions."""
    tenant, agent = f"t_{new_id()[:8]}", "a1"

    def make(content: str) -> MemoryRecord:
        return MemoryRecord(
            tenant_id=tenant, agent_id=agent, type=MemoryType.SEMANTIC, content=content
        )

    # add / get / duplicate / isolation
    m1 = make("Chinmay prefers dark mode.")
    await store.add(m1)
    fetched = await store.get(tenant, m1.id)
    assert fetched is not None and fetched.content == m1.content
    assert await store.get("other-tenant", m1.id) is None  # isolation
    try:
        await store.add(m1)
        raise AssertionError("duplicate add must raise ConflictError")
    except ConflictError:
        pass

    # list: newest-first, filtered by status/type
    m2 = make("Chinmay lives in India.")
    await store.add(m2)
    listed = await store.list_records(tenant, agent)
    assert [r.id for r in listed] == [m2.id, m1.id]
    assert await store.list_records(tenant, agent, type=MemoryType.EPISODIC) == []
    assert await store.list_records(tenant, "other-agent") == []

    # supersede: atomic version flip
    m1_v2 = m1.superseded_by(content="Chinmay prefers dark mode everywhere.")
    await store.supersede(tenant, m1.id, m1_v2)
    old = await store.get(tenant, m1.id)
    assert old is not None and old.status is MemoryStatus.SUPERSEDED
    active = await store.list_records(tenant, agent)
    assert {r.id for r in active} == {m2.id, m1_v2.id}

    # versions: full chain oldest-first, reachable from either end
    chain_from_old = await store.versions(tenant, m1.id)
    chain_from_new = await store.versions(tenant, m1_v2.id)
    assert [r.id for r in chain_from_old] == [m1.id, m1_v2.id]
    assert [r.id for r in chain_from_new] == [m1.id, m1_v2.id]

    # supersede of a missing id must raise
    try:
        await store.supersede(tenant, "missing", make("x"))
        raise AssertionError("supersede of missing id must raise NotFoundError")
    except NotFoundError:
        pass

    # set_status: soft delete hides from active list
    await store.set_status(tenant, m2.id, MemoryStatus.SOFT_DELETED)
    assert {r.id for r in await store.list_records(tenant, agent)} == {m1_v2.id}
    assert (
        len(await store.list_records(tenant, agent, status=None)) == 3
    )  # all statuses visible when unfiltered

    # reinforce
    now = utcnow()
    await store.reinforce(tenant, [m1_v2.id], now)
    reinforced = await store.get(tenant, m1_v2.id)
    assert reinforced is not None
    assert reinforced.access_count == m1_v2.access_count + 1
    assert reinforced.last_accessed_at is not None

    # audit: append-only, tenant-scoped, newest-first
    e1 = AuditEvent(tenant_id=tenant, actor="api", action=AuditAction.CREATE,
                    target_id=m1.id)
    e2 = AuditEvent(tenant_id=tenant, actor="api", action=AuditAction.UPDATE,
                    target_id=m1_v2.id)
    await store.add_audit(e1)
    await store.add_audit(e2)
    await store.add_audit(
        AuditEvent(tenant_id="other-tenant", actor="api", action=AuditAction.CREATE)
    )
    events = await store.list_audit(tenant)
    assert [e.id for e in events] == [e2.id, e1.id]

    # sessions: upsert + isolation
    sess = Session(tenant_id=tenant, agent_id=agent)
    await store.put_session(sess)
    got = await store.get_session(tenant, sess.id)
    assert got is not None and got.agent_id == agent and got.closed is False
    updated = sess.model_copy(update={"closed": True, "turn_count": 5})
    await store.put_session(updated)
    got2 = await store.get_session(tenant, sess.id)
    assert got2 is not None and got2.closed is True and got2.turn_count == 5
    assert await store.get_session("other-tenant", sess.id) is None
