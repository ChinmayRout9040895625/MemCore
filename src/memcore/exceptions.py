"""Typed exception hierarchy for MemCore.

All MemCore errors derive from :class:`MemCoreError` so callers can catch the
whole family, while specific subclasses map cleanly onto API problem+json
responses in the API phase.
"""

from __future__ import annotations


class MemCoreError(Exception):
    """Base class for all MemCore errors."""


class ConfigurationError(MemCoreError):
    """Invalid or missing configuration."""


class NotFoundError(MemCoreError):
    """A requested resource does not exist."""


class ValidationError(MemCoreError):
    """A request or payload failed domain validation."""


class ConflictError(MemCoreError):
    """An operation conflicts with current state (e.g. version clash)."""


class StorageError(MemCoreError):
    """A backing store (vector/graph/working/object) failed."""


class ProviderError(MemCoreError):
    """An external provider (LLM or embedding) failed."""


class TenantIsolationError(MemCoreError):
    """A cross-tenant access was attempted and blocked."""
