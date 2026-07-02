"""In-memory reference adapters.

These are correctness references and test doubles, not production stores. They
implement the ports faithfully (including tenant/agent filtering) so the core
and tests can run without any external service. They are process-local and
non-durable by design.
"""

from memcore.adapters.inmemory.embedding import HashingEmbeddingProvider
from memcore.adapters.inmemory.graph_store import InMemoryGraphStore
from memcore.adapters.inmemory.llm import ScriptedLLMProvider
from memcore.adapters.inmemory.memory_store import InMemoryMemoryStore
from memcore.adapters.inmemory.object_store import InMemoryObjectStore
from memcore.adapters.inmemory.vector_store import InMemoryVectorStore
from memcore.adapters.inmemory.workflow import ImmediateWorkflowEngine
from memcore.adapters.inmemory.working_memory import InMemoryWorkingMemory

__all__ = [
    "HashingEmbeddingProvider",
    "ImmediateWorkflowEngine",
    "InMemoryGraphStore",
    "InMemoryMemoryStore",
    "InMemoryObjectStore",
    "InMemoryVectorStore",
    "InMemoryWorkingMemory",
    "ScriptedLLMProvider",
]
