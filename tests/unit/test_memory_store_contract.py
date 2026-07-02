"""MemoryStore contract against both adapters (in-memory and SQL/SQLite)."""

from __future__ import annotations

from memcore.adapters.inmemory import InMemoryMemoryStore
from memcore.adapters.sql import SqlMemoryStore
from memcore.testing import check_memory_store_contract


async def test_inmemory_memory_store_contract() -> None:
    await check_memory_store_contract(InMemoryMemoryStore())


async def test_sql_memory_store_contract_sqlite() -> None:
    store = SqlMemoryStore("sqlite+aiosqlite:///:memory:")
    await store.init()
    try:
        await check_memory_store_contract(store)
    finally:
        await store.close()
