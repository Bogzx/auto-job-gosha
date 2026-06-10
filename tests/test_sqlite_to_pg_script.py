"""Tests for the one-time SQLite -> Postgres data copy script.

The copy logic is database-agnostic (SQLAlchemy), so the test exercises it
with two SQLite files; production runs it with a postgresql+asyncpg dst URL.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gosha.events import Event
from gosha.models import (
    Application,
    Base,
    CoverLetter,
    Job,
    Subscription,
    User,
    UserJob,
)

from scripts.migrate_sqlite_to_postgres import copy_all


@pytest.mark.asyncio
async def test_copy_all_moves_every_table(tmp_path):
    src_url = f"sqlite+aiosqlite:///{tmp_path / 'src.db'}"
    dst_url = f"sqlite+aiosqlite:///{tmp_path / 'dst.db'}"

    # Seed the source database
    src_engine = create_async_engine(src_url)
    async with src_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(src_engine, expire_on_commit=False)
    async with factory() as session:
        user = User(discord_user_id=111, username="gosha", tier="pro")
        session.add(user)
        await session.flush()

        job1 = Job(url="https://x/1", title="Dev", company="A", source="indeed")
        job2 = Job(url="https://x/2", title="QA", company="B", source="linkedin")
        session.add_all([job1, job2])
        await session.flush()

        sub = Subscription(user_id=user.id)
        sub.keywords = ["dev"]
        sub.locations = ["cluj"]
        session.add(sub)
        await session.flush()

        session.add_all([
            UserJob(user_id=user.id, job_id=job1.id, subscription_id=sub.id),
            Application(user_id=user.id, job_id=job1.id, status="interview"),
            CoverLetter(user_id=user.id, job_id=job1.id, content="Dear..."),
            Event(event_type="job.discovered", job_id=job1.id),
            Event(event_type="web.signin", actor_id=user.id),
            Event(event_type="user.feedback", actor_id=user.id, job_id=job1.id),
        ])
        await session.commit()
    await src_engine.dispose()

    copied = await copy_all(src_url, dst_url)

    assert copied["users"] == 1
    assert copied["jobs"] == 2
    assert copied["subscriptions"] == 1
    assert copied["user_jobs"] == 1
    assert copied["applications"] == 1
    assert copied["cover_letters"] == 1
    assert copied["events"] == 3
    assert copied["outbox"] == 0

    # Verify integrity in the destination
    dst_engine = create_async_engine(dst_url)
    dst_factory = async_sessionmaker(dst_engine, expire_on_commit=False)
    async with dst_factory() as session:
        u = (await session.execute(select(User))).scalar_one()
        assert u.discord_user_id == 111
        assert u.tier == "pro"

        s = (await session.execute(select(Subscription))).scalar_one()
        assert s.keywords == ["dev"]
        assert s.user_id == u.id

        n_jobs = (await session.execute(select(func.count(Job.id)))).scalar()
        assert n_jobs == 2
    await dst_engine.dispose()


@pytest.mark.asyncio
async def test_copy_all_sanitizes_broken_foreign_keys(tmp_path):
    """Old SQLite data can reference deleted rows — nullable FKs get nulled,
    rows with broken required FKs get dropped."""
    src_url = f"sqlite+aiosqlite:///{tmp_path / 'src3.db'}"
    dst_url = f"sqlite+aiosqlite:///{tmp_path / 'dst3.db'}"

    src_engine = create_async_engine(src_url)
    async with src_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(src_engine, expire_on_commit=False)
    async with factory() as session:
        user = User(discord_user_id=222)
        session.add(user)
        await session.flush()
        job = Job(url="https://x/ok", title="Dev", company="A", source="indeed")
        session.add(job)
        await session.flush()
        session.add_all([
            # subscription_id=999 doesn't exist -> nulled (nullable FK)
            UserJob(user_id=user.id, job_id=job.id, subscription_id=999),
        ])
        await session.commit()
        # job_id=12345 doesn't exist -> row dropped (required FK).
        # Insert via raw SQL since SQLite won't enforce it here.
        from sqlalchemy import text
        await session.execute(text(
            f"INSERT INTO applications (user_id, job_id, status, source, applied_at, updated_at) "
            f"VALUES ({user.id}, 12345, 'applied', 'discord', '2026-01-01', '2026-01-01')"
        ))
        await session.commit()
    await src_engine.dispose()

    copied = await copy_all(src_url, dst_url)

    assert copied["user_jobs"] == 1
    assert copied["applications"] == 0  # broken row dropped

    dst_engine = create_async_engine(dst_url)
    dst_factory = async_sessionmaker(dst_engine, expire_on_commit=False)
    async with dst_factory() as session:
        uj = (await session.execute(select(UserJob))).scalar_one()
        assert uj.subscription_id is None  # broken ref nulled
    await dst_engine.dispose()


@pytest.mark.asyncio
async def test_copy_all_refuses_nonempty_destination(tmp_path):
    src_url = f"sqlite+aiosqlite:///{tmp_path / 'src2.db'}"
    dst_url = f"sqlite+aiosqlite:///{tmp_path / 'dst2.db'}"

    for url in (src_url, dst_url):
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add(User(discord_user_id=1))
            await session.commit()
        await engine.dispose()

    with pytest.raises(RuntimeError, match="not empty"):
        await copy_all(src_url, dst_url)
