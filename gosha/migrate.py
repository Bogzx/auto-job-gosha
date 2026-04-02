"""Database migration from old flat schema to new GOSHA schema.

Handles:
  - subscriptions: keyword/location (single strings) → keywords/locations (JSON lists)
  - seen_jobs → user_jobs: preserve delivery history so users aren't re-notified
  - new tables: jobs, events created by create_all()
  - new columns on subscriptions: defaults applied for old rows

Run automatically on startup (idempotent — safe to run multiple times).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

log = logging.getLogger(__name__)


async def run_migrations(conn: AsyncConnection) -> None:
    """Run all migrations inside an existing connection/transaction."""
    inspector = await conn.run_sync(lambda sync_conn: inspect(sync_conn))
    existing_tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    log.info("Existing tables: %s", existing_tables)

    # 1. Migrate subscriptions if old schema detected
    if "subscriptions" in existing_tables:
        await _migrate_subscriptions(conn, inspector)

    # 2. Migrate seen_jobs → user_jobs
    if "seen_jobs" in existing_tables:
        await _migrate_seen_jobs(conn, existing_tables)

    log.info("Migration complete.")


async def _migrate_subscriptions(conn: AsyncConnection, inspector) -> None:
    """Migrate old subscription columns to new JSON-list format."""
    columns = await conn.run_sync(
        lambda sync_conn: [c["name"] for c in inspect(sync_conn).get_columns("subscriptions")]
    )

    has_old_keyword = "keyword" in columns
    has_new_keywords = "keywords" in columns

    # Case 1: Old schema only (keyword, location) — need full migration
    if has_old_keyword and not has_new_keywords:
        log.info("Detected old subscription schema — migrating...")

        # Add new columns
        new_cols = [
            ("keywords", "TEXT"),
            ("locations", "TEXT"),
            ("excluded_keywords", "TEXT DEFAULT '[]'"),
            ("company_blacklist", "TEXT DEFAULT '[]'"),
            ("boards", "TEXT DEFAULT '[\"indeed\",\"linkedin\",\"glassdoor\"]'"),
            ("experience_levels", "TEXT DEFAULT '[\"any\"]'"),
            ("remote_ok", "BOOLEAN DEFAULT 0"),
            ("salary_min", "INTEGER"),
            ("is_active", "BOOLEAN DEFAULT 1"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in columns:
                try:
                    await conn.execute(text(
                        f"ALTER TABLE subscriptions ADD COLUMN {col_name} {col_type}"
                    ))
                    log.info("Added column: subscriptions.%s", col_name)
                except Exception as e:
                    # Column might already exist in some edge case
                    log.debug("Column %s may already exist: %s", col_name, e)

        # Copy data from old columns to new JSON format
        await conn.execute(text("""
            UPDATE subscriptions
            SET keywords = '["' || REPLACE(keyword, '"', '\\"') || '"]',
                locations = '["' || REPLACE(location, '"', '\\"') || '"]'
            WHERE keywords IS NULL AND keyword IS NOT NULL
        """))
        log.info("Migrated keyword/location → keywords/locations (JSON)")

        # Set defaults for new columns where NULL
        await conn.execute(text("""
            UPDATE subscriptions SET excluded_keywords = '[]' WHERE excluded_keywords IS NULL
        """))
        await conn.execute(text("""
            UPDATE subscriptions SET company_blacklist = '[]' WHERE company_blacklist IS NULL
        """))
        await conn.execute(text("""
            UPDATE subscriptions SET boards = '["indeed","linkedin","glassdoor"]' WHERE boards IS NULL
        """))
        await conn.execute(text("""
            UPDATE subscriptions SET experience_levels = '["any"]' WHERE experience_levels IS NULL
        """))
        await conn.execute(text("""
            UPDATE subscriptions SET is_active = 1 WHERE is_active IS NULL
        """))
        await conn.execute(text("""
            UPDATE subscriptions SET remote_ok = 0 WHERE remote_ok IS NULL
        """))
        log.info("Applied defaults to new subscription columns.")

    # Case 2: Both old and new columns exist (partially migrated)
    elif has_old_keyword and has_new_keywords:
        # Fill any remaining NULL keywords from old keyword column
        await conn.execute(text("""
            UPDATE subscriptions
            SET keywords = '["' || REPLACE(keyword, '"', '\\"') || '"]'
            WHERE keywords IS NULL AND keyword IS NOT NULL
        """))
        await conn.execute(text("""
            UPDATE subscriptions
            SET locations = '["' || REPLACE(location, '"', '\\"') || '"]'
            WHERE locations IS NULL AND location IS NOT NULL
        """))
        log.info("Backfilled any remaining NULL keywords/locations from old columns.")

    # Case 3: New schema only — nothing to do
    elif has_new_keywords:
        log.info("Subscription schema is already new format.")


async def _migrate_seen_jobs(conn: AsyncConnection, existing_tables: list[str]) -> None:
    """Migrate seen_jobs records into user_jobs to preserve delivery history.

    Creates a stub Job record for each unique URL, then maps seen_jobs → user_jobs.
    This prevents users from being re-notified about jobs they already saw.
    """
    has_user_jobs = "user_jobs" in existing_tables
    has_jobs = "jobs" in existing_tables

    # Tables might not exist yet (create_all runs after migration)
    # We'll create them manually if needed
    if not has_jobs:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url VARCHAR(1024) UNIQUE NOT NULL,
                title VARCHAR(512) NOT NULL DEFAULT 'Unknown',
                company VARCHAR(256) NOT NULL DEFAULT 'Unknown',
                location VARCHAR(256) NOT NULL DEFAULT '',
                description TEXT,
                salary_min FLOAT,
                salary_max FLOAT,
                salary_currency VARCHAR(16),
                source VARCHAR(64) NOT NULL DEFAULT 'migrated',
                is_active BOOLEAN NOT NULL DEFAULT 1,
                first_seen_at DATETIME,
                last_seen_at DATETIME
            )
        """))
        log.info("Created jobs table for migration.")

    if not has_user_jobs:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                job_id INTEGER NOT NULL REFERENCES jobs(id),
                subscription_id INTEGER,
                relevance_score FLOAT,
                delivered_at DATETIME,
                feedback VARCHAR(32),
                feedback_at DATETIME,
                UNIQUE(user_id, job_id)
            )
        """))
        log.info("Created user_jobs table for migration.")

    # Check if migration already happened (seen_jobs might be empty or already processed)
    result = await conn.execute(text("SELECT COUNT(*) FROM seen_jobs"))
    seen_count = result.scalar()
    if seen_count == 0:
        log.info("seen_jobs is empty — nothing to migrate.")
        return

    # Check if we already migrated (user_jobs has data)
    result = await conn.execute(text("SELECT COUNT(*) FROM user_jobs"))
    uj_count = result.scalar()
    if uj_count > 0:
        log.info("user_jobs already has %d records — skipping seen_jobs migration.", uj_count)
        return

    log.info("Migrating %d seen_jobs records...", seen_count)
    now = datetime.now(timezone.utc).isoformat()

    # Step 1: Create stub Job records for each unique URL
    await conn.execute(text(f"""
        INSERT OR IGNORE INTO jobs (url, title, company, source, is_active, first_seen_at, last_seen_at)
        SELECT DISTINCT job_url, 'Unknown (migrated)', 'Unknown', 'migrated', 1, '{now}', '{now}'
        FROM seen_jobs
        WHERE job_url IS NOT NULL AND job_url != ''
    """))

    # Step 2: Map seen_jobs → user_jobs via the stub Job records
    await conn.execute(text(f"""
        INSERT OR IGNORE INTO user_jobs (user_id, job_id, delivered_at)
        SELECT sj.user_id, j.id, COALESCE(sj.seen_at, '{now}')
        FROM seen_jobs sj
        JOIN jobs j ON j.url = sj.job_url
    """))

    result = await conn.execute(text("SELECT COUNT(*) FROM user_jobs"))
    migrated = result.scalar()
    log.info("Migrated %d seen_jobs → user_jobs records.", migrated)
