"""MemCore test-kit: reusable port conformance checks.

Shipped as part of the package (not just the test tree) so that:

* MemCore's own unit tests validate the in-memory adapters, and its integration
  tests validate the live Qdrant/Neo4j/Redis adapters, against the *same* spec.
* Third parties writing their own adapters can assert conformance to the port
  contracts with a single call.

Each ``check_*_contract`` coroutine exercises a fresh store and asserts the
behavioural guarantees of its port (isolation, ordering, bounding, round-trip).
"""

from memcore.testing.contracts import (
    check_graph_store_contract,
    check_memory_store_contract,
    check_object_store_contract,
    check_vector_store_contract,
    check_working_memory_contract,
)

__all__ = [
    "check_graph_store_contract",
    "check_memory_store_contract",
    "check_object_store_contract",
    "check_vector_store_contract",
    "check_working_memory_contract",
]
