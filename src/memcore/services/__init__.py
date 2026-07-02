"""MemCore services: the use-case layer between the API and the ports.

Routes stay thin; services own the orchestration (archive-on-ingest, versioned
correction, audit emission, hybrid scoring v1).
"""

from memcore.services.consolidation import ConsolidationReport, ConsolidationService
from memcore.services.context import assemble_context
from memcore.services.memories import MemoryService
from memcore.services.recall import RecallService, ScoreWeights
from memcore.services.sessions import SessionService

__all__ = [
    "ConsolidationReport",
    "ConsolidationService",
    "MemoryService",
    "RecallService",
    "ScoreWeights",
    "SessionService",
    "assemble_context",
]
