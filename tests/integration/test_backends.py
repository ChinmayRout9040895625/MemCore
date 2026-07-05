"""Integration tests for the live storage adapters.

Each test runs the shipped port contract against a real backend, and *skips*
cleanly when the backend is not reachable — so the suite is safe to run locally
without Docker, while exercising real Qdrant/Neo4j/Redis in CI when services are
provided. Connection targets come from the standard ``MEMCORE_*`` env vars.

Run explicitly with:  pytest -m integration
"""

from __future__ import annotations

import os

import pytest

from memcore.testing import (
    check_graph_store_contract,
    check_vector_store_contract,
    check_working_memory_contract,
)

pytestmark = pytest.mark.integration


async def test_qdrant_vector_store_contract() -> None:
    from memcore.adapters.qdrant import QdrantVectorStore

    url = os.getenv("MEMCORE_VECTOR__URL", "http://localhost:6333")
    store = QdrantVectorStore(url, os.getenv("MEMCORE_VECTOR__API_KEY") or None)
    try:
        await store._client.get_collections()
    except Exception:
        await store.close()
        pytest.skip(f"Qdrant not reachable at {url}")
    try:
        await store.ping()
        await check_vector_store_contract(store)
    finally:
        await store.close()


async def test_redis_working_memory_contract() -> None:
    from memcore.adapters.redis import RedisWorkingMemory

    url = os.getenv("MEMCORE_REDIS__URL", "redis://localhost:6379/0")
    store = RedisWorkingMemory(url, buffer_max_turns=5)
    try:
        await store._redis.ping()
    except Exception:
        await store.close()
        pytest.skip(f"Redis not reachable at {url}")
    try:
        await store.ping()
        await check_working_memory_contract(store)
    finally:
        await store.close()


async def test_neo4j_graph_store_contract() -> None:
    from memcore.adapters.neo4j import Neo4jGraphStore

    url = os.getenv("MEMCORE_GRAPH__URL", "bolt://localhost:7687")
    user = os.getenv("MEMCORE_GRAPH__USER", "neo4j")
    password = os.getenv("MEMCORE_GRAPH__PASSWORD", "memcore-dev-password")
    store = Neo4jGraphStore(url, user, password)
    try:
        await store._driver.verify_connectivity()
    except Exception:
        await store.close()
        pytest.skip(f"Neo4j not reachable at {url}")
    try:
        await store.ping()
        await check_graph_store_contract(store)
    finally:
        await store.close()
