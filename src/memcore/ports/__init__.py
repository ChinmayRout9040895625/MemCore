"""MemCore ports: abstract interfaces that decouple the core from backends.

Every external dependency (vector DB, graph DB, working memory, LLM, embedding
model, workflow engine, object store) is expressed here as an abstract base
class. Concrete adapters live under ``memcore.adapters`` and must not leak
driver-specific types across these boundaries (ADR-006).
"""

from memcore.ports.embedding_provider import EmbeddingProvider
from memcore.ports.graph_store import GraphStore
from memcore.ports.llm_provider import LLMProvider
from memcore.ports.memory_store import MemoryStore
from memcore.ports.object_store import ObjectStore
from memcore.ports.vector_store import VectorHit, VectorRecord, VectorStore
from memcore.ports.workflow_engine import JobHandle, JobState, WorkflowEngine
from memcore.ports.working_memory import WorkingMemory

__all__ = [
    "EmbeddingProvider",
    "GraphStore",
    "JobHandle",
    "JobState",
    "LLMProvider",
    "MemoryStore",
    "ObjectStore",
    "VectorHit",
    "VectorRecord",
    "VectorStore",
    "WorkflowEngine",
    "WorkingMemory",
]
