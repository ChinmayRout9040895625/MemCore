"""Run the shipped port-contract checks against the in-memory adapters.

These validate both the in-memory reference adapters and the contract kit
itself; the integration suite reuses the same checks against live backends.
"""

from __future__ import annotations

from memcore.adapters.inmemory import (
    InMemoryGraphStore,
    InMemoryObjectStore,
    InMemoryVectorStore,
    InMemoryWorkingMemory,
)
from memcore.testing import (
    check_graph_store_contract,
    check_object_store_contract,
    check_vector_store_contract,
    check_working_memory_contract,
)


async def test_inmemory_vector_contract() -> None:
    await check_vector_store_contract(InMemoryVectorStore())


async def test_inmemory_working_memory_contract() -> None:
    await check_working_memory_contract(InMemoryWorkingMemory())


async def test_inmemory_object_contract() -> None:
    await check_object_store_contract(InMemoryObjectStore())


async def test_inmemory_graph_contract() -> None:
    await check_graph_store_contract(InMemoryGraphStore())
