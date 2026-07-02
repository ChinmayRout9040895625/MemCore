"""MemCore — long-term memory infrastructure for AI agents.

Public surface is intentionally small in Phase 1: domain models, ports, config,
and errors. Higher-level services (ingest, recall, consolidation) arrive in
later phases and will be re-exported here as they stabilize.
"""

from memcore.config import Settings, load_settings
from memcore.exceptions import (
    ConfigurationError,
    ConflictError,
    MemCoreError,
    NotFoundError,
    ProviderError,
    StorageError,
    TenantIsolationError,
    ValidationError,
)

__version__ = "0.1.0"

__all__ = [
    "ConfigurationError",
    "ConflictError",
    "MemCoreError",
    "NotFoundError",
    "ProviderError",
    "Settings",
    "StorageError",
    "TenantIsolationError",
    "ValidationError",
    "__version__",
    "load_settings",
]
