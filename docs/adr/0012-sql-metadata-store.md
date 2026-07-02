# ADR-0012: SQL metadata store via SQLAlchemy (Postgres prod, SQLite tests)

**Status:** Accepted (2026-07-02)

## Context
ADR-0005 makes a relational store the source of truth for memory records,
audit and sessions. We need it testable without infrastructure and deployable
on Postgres.

## Decision
One `SqlMemoryStore` adapter on SQLAlchemy 2 async:
- **Postgres (asyncpg)** in production; **SQLite (aiosqlite)** for tests and
  lightweight self-hosting — same code path, different URL.
- Datetimes stored as **ISO-8601 strings (UTC)**: identical semantics and
  correct lexicographic ordering on both engines. Migration to native
  `timestamptz` is deliberate future work, behind the port.
- Enums stored by value; lists/dicts as JSON columns.
- `supersede` (the ADR-0007 version flip) executes in a single transaction.
- Schema creation is `create_all` at startup for now; migration tooling
  (alembic) arrives before any production deployment.

The `MemoryStore` port also gets an in-memory reference adapter and a shipped
contract check (`check_memory_store_contract`), same policy as ADR-0011.

## Consequences
- CI exercises the real SQL adapter (SQLite) on every run — not just a fake.
- ISO-string datetimes trade native DB time arithmetic for portability; decay
  jobs computing in SQL will need casting or the future migration.
- The API/services depend only on the port; swapping SQLite→Postgres is a URL.
