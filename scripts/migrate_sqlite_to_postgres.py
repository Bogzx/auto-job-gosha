"""One-time data copy from the SQLite database to Postgres.

Usage:
    python scripts/migrate_sqlite_to_postgres.py \
        sqlite+aiosqlite:///data/jobs.db \
        postgresql+asyncpg://gosha:PASSWORD@localhost:5432/gosha

The destination schema is created from the current models; the destination
must be empty (no users) so a half-done copy can't silently merge. Primary
keys are preserved so foreign keys stay valid; Postgres sequences are reset
afterwards.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from gosha.events import Event
from gosha.models import (
    Application,
    Base,
    CoverLetter,
    Job,
    Outbox,
    Subscription,
    User,
    UserJob,
)

log = logging.getLogger(__name__)

# Copy order respects foreign-key dependencies.
TABLES = [
    User.__table__,
    Job.__table__,
    Subscription.__table__,
    UserJob.__table__,
    Application.__table__,
    CoverLetter.__table__,
    Event.__table__,
    Outbox.__table__,
]

BATCH_SIZE = 1000


async def copy_all(src_url: str, dst_url: str) -> dict[str, int]:
    """Copy every table from src to dst. Returns row counts per table."""
    src = create_async_engine(src_url)
    dst = create_async_engine(dst_url)
    copied: dict[str, int] = {}

    try:
        async with dst.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            existing_users = (
                await conn.execute(select(func.count()).select_from(User.__table__))
            ).scalar()
            if existing_users:
                raise RuntimeError(
                    f"Destination database is not empty ({existing_users} users) — "
                    "refusing to copy into it."
                )

        for table in TABLES:
            async with src.connect() as src_conn:
                rows = (await src_conn.execute(select(table))).mappings().all()

            async with dst.begin() as dst_conn:
                for start in range(0, len(rows), BATCH_SIZE):
                    batch = [dict(r) for r in rows[start : start + BATCH_SIZE]]
                    if batch:
                        await dst_conn.execute(insert(table), batch)

            copied[table.name] = len(rows)
            log.info("Copied %5d rows -> %s", len(rows), table.name)

        # Postgres: bump sequences past the copied primary keys.
        if dst.dialect.name == "postgresql":
            async with dst.begin() as conn:
                for table in TABLES:
                    await conn.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table.name}), 1))"
                    ))
    finally:
        await src.dispose()
        await dst.dispose()

    return copied


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    counts = asyncio.run(copy_all(sys.argv[1], sys.argv[2]))
    total = sum(counts.values())
    print(f"Done — {total} rows copied across {len(counts)} tables.")


if __name__ == "__main__":
    main()
