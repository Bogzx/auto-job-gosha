"""Event sourcing — immutable event log for full audit trail and analytics.

All significant state changes are recorded as events. Events can be replayed
to rebuild derived state, debug delivery issues, or power analytics.

Event types:
  - JobDiscovered   — a new job was scraped and stored
  - JobUpdated      — an existing job was re-seen and updated
  - JobExpired      — a job was marked inactive
  - JobMatched      — a job matched a subscription for a user
  - JobDelivered    — a notification was sent to a user
  - UserFeedback    — user reacted to a delivered job
  - SubscriptionCreated / Updated / Paused / Deleted
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column

from gosha.models import Base

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Event(Base):
    """Immutable event record."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    # Optional foreign keys stored as ints (not FK constraints — events are immutable)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # user ID
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscription_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # JSON payload for event-specific data
    _payload: Mapped[str] = mapped_column("payload", Text, nullable=False, default="{}")

    @property
    def payload(self) -> dict:
        try:
            return json.loads(self._payload)
        except (json.JSONDecodeError, TypeError):
            return {}

    @payload.setter
    def payload(self, value: dict) -> None:
        self._payload = json.dumps(value, default=str)

    def __repr__(self) -> str:
        return (
            f"<Event {self.event_type} id={self.id} "
            f"job_id={self.job_id} actor_id={self.actor_id}>"
        )


# ---------------------------------------------------------------------------
# Event store — write and query events
# ---------------------------------------------------------------------------


class EventStore:
    """Async event store backed by the events table."""

    async def emit(
        self,
        event_type: str,
        actor_id: int | None = None,
        job_id: int | None = None,
        subscription_id: int | None = None,
        payload: dict | None = None,
    ) -> Event:
        """Record an event."""
        from gosha.database import get_session

        event = Event(
            event_type=event_type,
            actor_id=actor_id,
            job_id=job_id,
            subscription_id=subscription_id,
        )
        if payload:
            event.payload = payload

        async with get_session() as session:
            session.add(event)
            await session.commit()

        log.debug("Event: %s (job=%s, actor=%s)", event_type, job_id, actor_id)
        return event

    async def emit_batch(self, events_data: list[dict]) -> int:
        """Record multiple events in one transaction."""
        from gosha.database import get_session

        if not events_data:
            return 0

        async with get_session() as session:
            for data in events_data:
                event = Event(
                    event_type=data["event_type"],
                    actor_id=data.get("actor_id"),
                    job_id=data.get("job_id"),
                    subscription_id=data.get("subscription_id"),
                )
                if "payload" in data:
                    event.payload = data["payload"]
                session.add(event)
            await session.commit()

        return len(events_data)

    async def query(
        self,
        event_type: str | None = None,
        actor_id: int | None = None,
        job_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Query events with optional filters."""
        from gosha.database import get_session

        stmt = select(Event)
        if event_type:
            stmt = stmt.where(Event.event_type == event_type)
        if actor_id is not None:
            stmt = stmt.where(Event.actor_id == actor_id)
        if job_id is not None:
            stmt = stmt.where(Event.job_id == job_id)
        if since:
            stmt = stmt.where(Event.timestamp >= since)
        if until:
            stmt = stmt.where(Event.timestamp <= until)

        stmt = stmt.order_by(Event.timestamp.desc()).limit(limit)

        async with get_session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def count_by_type(
        self,
        since: datetime | None = None,
    ) -> dict[str, int]:
        """Count events grouped by type."""
        from gosha.database import get_session

        stmt = select(Event.event_type, func.count(Event.id)).group_by(Event.event_type)
        if since:
            stmt = stmt.where(Event.timestamp >= since)

        async with get_session() as session:
            result = await session.execute(stmt)
            return {event_type: count for event_type, count in result.all()}


# ---------------------------------------------------------------------------
# Convenience functions for common events
# ---------------------------------------------------------------------------


# Global event store instance
_store = EventStore()


async def emit_job_discovered(job_id: int, source: str, url: str) -> Event:
    return await _store.emit(
        "job.discovered",
        job_id=job_id,
        payload={"source": source, "url": url},
    )


async def emit_job_updated(job_id: int) -> Event:
    return await _store.emit("job.updated", job_id=job_id)


async def emit_job_expired(job_id: int) -> Event:
    return await _store.emit("job.expired", job_id=job_id)


async def emit_job_matched(
    job_id: int, user_id: int, subscription_id: int, score: float
) -> Event:
    return await _store.emit(
        "job.matched",
        actor_id=user_id,
        job_id=job_id,
        subscription_id=subscription_id,
        payload={"score": score},
    )


async def emit_job_delivered(
    job_id: int, user_id: int, channel: str
) -> Event:
    return await _store.emit(
        "job.delivered",
        actor_id=user_id,
        job_id=job_id,
        payload={"channel": channel},
    )


async def emit_user_feedback(
    job_id: int, user_id: int, feedback: str
) -> Event:
    return await _store.emit(
        "user.feedback",
        actor_id=user_id,
        job_id=job_id,
        payload={"feedback": feedback},
    )


async def emit_subscription_created(
    user_id: int, subscription_id: int, keywords: list[str]
) -> Event:
    return await _store.emit(
        "subscription.created",
        actor_id=user_id,
        subscription_id=subscription_id,
        payload={"keywords": keywords},
    )


async def emit_subscription_paused(user_id: int, subscription_id: int) -> Event:
    return await _store.emit(
        "subscription.paused",
        actor_id=user_id,
        subscription_id=subscription_id,
    )


async def emit_subscription_deleted(user_id: int, subscription_id: int) -> Event:
    return await _store.emit(
        "subscription.deleted",
        actor_id=user_id,
        subscription_id=subscription_id,
    )


def get_event_store() -> EventStore:
    """Get the global event store instance."""
    return _store
