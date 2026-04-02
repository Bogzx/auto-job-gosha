"""Tests for the DB-backed delivery queue."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gosha.models import Job, Subscription, User, UserJob


@pytest_asyncio.fixture
async def patched_db(engine, monkeypatch):
    """Patch gosha.database globals so queue functions use the test engine."""
    import gosha.database as db_mod

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "_engine", engine)
    monkeypatch.setattr(db_mod, "_session_factory", factory)
    yield factory


@pytest_asyncio.fixture
async def users_and_jobs(session: AsyncSession):
    """Create test users and jobs."""
    u1 = User(discord_user_id=1001)
    u2 = User(discord_user_id=1002)
    session.add_all([u1, u2])
    await session.flush()

    j1 = Job(url="https://q.com/1", title="Dev A", company="Co1", source="indeed")
    j2 = Job(url="https://q.com/2", title="Dev B", company="Co2", source="linkedin")
    j3 = Job(url="https://q.com/3", title="Dev C", company="Co3", source="glassdoor")
    session.add_all([j1, j2, j3])
    await session.commit()

    return {"users": [u1, u2], "jobs": [j1, j2, j3]}


# ── enqueue_delivery ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enqueue_delivery_single(patched_db, users_and_jobs):
    from gosha.queue import enqueue_delivery

    data = users_and_jobs
    u1 = data["users"][0]
    j1 = data["jobs"][0]

    uj = await enqueue_delivery(u1.id, j1.id, relevance_score=0.9)
    assert uj is not None
    assert uj.user_id == u1.id
    assert uj.job_id == j1.id
    assert uj.relevance_score == 0.9


@pytest.mark.asyncio
async def test_enqueue_delivery_duplicate_returns_none(patched_db, users_and_jobs):
    from gosha.queue import enqueue_delivery

    data = users_and_jobs
    u1 = data["users"][0]
    j1 = data["jobs"][0]

    first = await enqueue_delivery(u1.id, j1.id)
    assert first is not None

    second = await enqueue_delivery(u1.id, j1.id)
    assert second is None


@pytest.mark.asyncio
async def test_enqueue_delivery_different_users(patched_db, users_and_jobs):
    from gosha.queue import enqueue_delivery

    data = users_and_jobs
    u1, u2 = data["users"]
    j1 = data["jobs"][0]

    uj1 = await enqueue_delivery(u1.id, j1.id)
    uj2 = await enqueue_delivery(u2.id, j1.id)
    assert uj1 is not None
    assert uj2 is not None


# ── enqueue_deliveries_batch ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_enqueue(patched_db, users_and_jobs):
    from gosha.queue import enqueue_deliveries_batch

    data = users_and_jobs
    u1, u2 = data["users"]
    j1, j2, j3 = data["jobs"]

    items = [
        {"user_id": u1.id, "job_id": j1.id, "subscription_id": None, "score": 0.8},
        {"user_id": u1.id, "job_id": j2.id, "subscription_id": None, "score": 0.7},
        {"user_id": u2.id, "job_id": j1.id, "subscription_id": None, "score": 0.9},
    ]

    created = await enqueue_deliveries_batch(items)
    assert created == 3


@pytest.mark.asyncio
async def test_batch_enqueue_skips_existing(patched_db, users_and_jobs):
    from gosha.queue import enqueue_deliveries_batch, enqueue_delivery

    data = users_and_jobs
    u1 = data["users"][0]
    j1, j2 = data["jobs"][:2]

    # Pre-deliver j1 to u1
    await enqueue_delivery(u1.id, j1.id)

    items = [
        {"user_id": u1.id, "job_id": j1.id, "score": 0.5},  # duplicate
        {"user_id": u1.id, "job_id": j2.id, "score": 0.8},  # new
    ]

    created = await enqueue_deliveries_batch(items)
    assert created == 1


@pytest.mark.asyncio
async def test_batch_enqueue_handles_in_batch_duplicates(patched_db, users_and_jobs):
    from gosha.queue import enqueue_deliveries_batch

    data = users_and_jobs
    u1 = data["users"][0]
    j1 = data["jobs"][0]

    # Same delivery twice in one batch
    items = [
        {"user_id": u1.id, "job_id": j1.id, "score": 0.8},
        {"user_id": u1.id, "job_id": j1.id, "score": 0.9},
    ]

    created = await enqueue_deliveries_batch(items)
    assert created == 1


@pytest.mark.asyncio
async def test_batch_enqueue_empty(patched_db):
    from gosha.queue import enqueue_deliveries_batch

    created = await enqueue_deliveries_batch([])
    assert created == 0


# ── get_fresh_jobs ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_fresh_jobs(patched_db, session: AsyncSession):
    from gosha.queue import get_fresh_jobs

    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=48)

    j_old = Job(
        url="https://old.com/1", title="Old", company="X", source="x",
        last_seen_at=old, first_seen_at=old,
    )
    j_new = Job(
        url="https://new.com/1", title="New", company="Y", source="y",
        last_seen_at=now, first_seen_at=now,
    )
    session.add_all([j_old, j_new])
    await session.commit()

    since = now - timedelta(hours=1)
    fresh = await get_fresh_jobs(since)
    assert len(fresh) == 1
    assert fresh[0].title == "New"


@pytest.mark.asyncio
async def test_get_fresh_jobs_excludes_inactive(patched_db, session: AsyncSession):
    from gosha.queue import get_fresh_jobs

    now = datetime.now(timezone.utc)
    j = Job(
        url="https://inactive.com/1", title="Inactive", company="X", source="x",
        last_seen_at=now, first_seen_at=now, is_active=False,
    )
    session.add(j)
    await session.commit()

    since = now - timedelta(hours=1)
    fresh = await get_fresh_jobs(since)
    assert len(fresh) == 0


# ── get_delivery_stats ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delivery_stats(patched_db, users_and_jobs, session: AsyncSession):
    from gosha.queue import get_delivery_stats

    data = users_and_jobs
    u1 = data["users"][0]
    j1, j2, j3 = data["jobs"]

    # Create deliveries with different feedback
    uj1 = UserJob(user_id=u1.id, job_id=j1.id, feedback="interested")
    uj2 = UserJob(user_id=u1.id, job_id=j2.id, feedback="not_relevant")
    uj3 = UserJob(user_id=u1.id, job_id=j3.id)  # no feedback
    session.add_all([uj1, uj2, uj3])
    await session.commit()

    stats = await get_delivery_stats()
    assert stats["total_delivered"] == 3
    assert stats["with_feedback"] == 2
    assert stats["interested"] == 1
    assert stats["not_relevant"] == 1
