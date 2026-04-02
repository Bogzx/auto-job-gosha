"""Tests for the event sourcing system."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from gosha.events import (
    Event,
    EventStore,
    emit_job_delivered,
    emit_job_discovered,
    emit_job_matched,
    emit_subscription_created,
    emit_user_feedback,
)


@pytest_asyncio.fixture
async def patched_db(engine, monkeypatch):
    import gosha.database as db_mod

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "_engine", engine)
    monkeypatch.setattr(db_mod, "_session_factory", factory)
    yield factory


@pytest.fixture
def store():
    return EventStore()


# ── EventStore.emit ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_basic(patched_db, store):
    event = await store.emit("test.event")
    assert event.id is not None
    assert event.event_type == "test.event"
    assert event.timestamp is not None


@pytest.mark.asyncio
async def test_emit_with_payload(patched_db, store):
    event = await store.emit(
        "test.payload",
        actor_id=1,
        job_id=42,
        payload={"key": "value", "count": 5},
    )
    assert event.payload == {"key": "value", "count": 5}
    assert event.actor_id == 1
    assert event.job_id == 42


@pytest.mark.asyncio
async def test_emit_batch(patched_db, store):
    events_data = [
        {"event_type": "batch.1", "job_id": 1},
        {"event_type": "batch.2", "job_id": 2, "payload": {"x": 1}},
        {"event_type": "batch.3", "actor_id": 5},
    ]
    count = await store.emit_batch(events_data)
    assert count == 3


@pytest.mark.asyncio
async def test_emit_batch_empty(patched_db, store):
    count = await store.emit_batch([])
    assert count == 0


# ── EventStore.query ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_by_type(patched_db, store):
    await store.emit("type.a")
    await store.emit("type.b")
    await store.emit("type.a")

    results = await store.query(event_type="type.a")
    assert len(results) == 2
    assert all(e.event_type == "type.a" for e in results)


@pytest.mark.asyncio
async def test_query_by_actor(patched_db, store):
    await store.emit("x", actor_id=10)
    await store.emit("x", actor_id=20)
    await store.emit("x", actor_id=10)

    results = await store.query(actor_id=10)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_query_by_job(patched_db, store):
    await store.emit("x", job_id=100)
    await store.emit("x", job_id=200)

    results = await store.query(job_id=100)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_query_since(patched_db, store):
    await store.emit("old")
    # All events are "now" in tests, so query with a past date
    now = datetime.now(timezone.utc)
    results = await store.query(since=now - timedelta(minutes=1))
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_query_limit(patched_db, store):
    for i in range(10):
        await store.emit("limit.test")

    results = await store.query(event_type="limit.test", limit=5)
    assert len(results) == 5


@pytest.mark.asyncio
async def test_query_ordered_desc(patched_db, store):
    await store.emit("order.1")
    await store.emit("order.2")

    results = await store.query(limit=10)
    # Most recent first
    assert results[0].timestamp >= results[-1].timestamp


# ── EventStore.count_by_type ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_count_by_type(patched_db, store):
    await store.emit("count.a")
    await store.emit("count.a")
    await store.emit("count.b")

    counts = await store.count_by_type()
    assert counts.get("count.a") == 2
    assert counts.get("count.b") == 1


# ── Convenience functions ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_job_discovered(patched_db):
    event = await emit_job_discovered(job_id=1, source="indeed", url="https://x.com/1")
    assert event.event_type == "job.discovered"
    assert event.job_id == 1
    assert event.payload["source"] == "indeed"


@pytest.mark.asyncio
async def test_emit_job_matched(patched_db):
    event = await emit_job_matched(job_id=5, user_id=2, subscription_id=3, score=0.85)
    assert event.event_type == "job.matched"
    assert event.actor_id == 2
    assert event.job_id == 5
    assert event.payload["score"] == 0.85


@pytest.mark.asyncio
async def test_emit_job_delivered(patched_db):
    event = await emit_job_delivered(job_id=10, user_id=1, channel="discord_dm")
    assert event.event_type == "job.delivered"
    assert event.payload["channel"] == "discord_dm"


@pytest.mark.asyncio
async def test_emit_user_feedback(patched_db):
    event = await emit_user_feedback(job_id=10, user_id=1, feedback="interested")
    assert event.event_type == "user.feedback"
    assert event.payload["feedback"] == "interested"


@pytest.mark.asyncio
async def test_emit_subscription_created(patched_db):
    event = await emit_subscription_created(
        user_id=1, subscription_id=5, keywords=["dev", "engineer"]
    )
    assert event.event_type == "subscription.created"
    assert event.payload["keywords"] == ["dev", "engineer"]


# ── Event model ───────────────────────────────────────────────────────


class TestEventModel:
    def test_payload_property(self):
        event = Event(event_type="test")
        event.payload = {"key": "val"}
        assert event.payload == {"key": "val"}

    def test_payload_default(self):
        event = Event(event_type="test")
        assert event.payload == {}

    def test_repr(self):
        event = Event(event_type="test", job_id=1, actor_id=2)
        event.id = 99
        r = repr(event)
        assert "test" in r
        assert "99" in r
