"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import gosha.events  # noqa: F401 — ensure Event model is registered with Base
from gosha.models import Base

log = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(database_url: str) -> AsyncEngine:
    """Create the async engine, session factory, and all tables.

    Runs migrations first to handle old → new schema upgrades,
    then create_all() to add any remaining new tables/columns.
    """
    global _engine, _session_factory

    _engine = create_async_engine(database_url, echo=False)

    # Enable WAL mode for safe concurrent access from bot + web
    if "sqlite" in database_url:

        @event.listens_for(_engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            try:
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()
            except Exception as exc:
                log.warning("Failed to set SQLite PRAGMAs: %s", exc)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    async with _engine.begin() as conn:
        # Run migrations BEFORE create_all so old columns are handled first
        try:
            from gosha.migrate import run_migrations
            await run_migrations(conn)
        except Exception as exc:
            log.warning("Migration step skipped (likely fresh DB): %s", exc)

        # create_all() is safe to run on an already-migrated DB —
        # it only adds tables/columns that don't exist yet.
        await conn.run_sync(Base.metadata.create_all)

    return _engine


def get_session() -> AsyncSession:
    """Return a new async session (caller must use ``async with``)."""
    if _session_factory is None:
        raise RuntimeError("Database not initialised — call init_db() first.")
    return _session_factory()


def get_engine() -> AsyncEngine:
    """Return the current engine (for testing / introspection)."""
    if _engine is None:
        raise RuntimeError("Database not initialised — call init_db() first.")
    return _engine
