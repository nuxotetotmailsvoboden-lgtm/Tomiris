# ADR 0001: PostgreSQL as storage

## Context
Signals require durable transactions and cross-process uniqueness.
## Decision
Use standard PostgreSQL through SQLAlchemy async and asyncpg, not a Supabase SDK or SQLite.
## Consequences
Local, Supabase and CI can share application logic; PostgreSQL is required for integration tests.

