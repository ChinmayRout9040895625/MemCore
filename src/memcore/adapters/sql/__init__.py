"""SQL adapter for the :class:`MemoryStore` port.

One adapter, any SQLAlchemy-async backend: Postgres (asyncpg) in production,
SQLite (aiosqlite) for tests and lightweight self-hosting.
"""

from memcore.adapters.sql.memory_store import SqlMemoryStore

__all__ = ["SqlMemoryStore"]
