"""Admin API: platform stats, usage charts, scrape health. Admin-only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from gosha.api.deps import admin_user
from gosha.database import get_session
from gosha.events import Event
from gosha.models import Application, Job, Subscription, User, UserJob

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def stats(_admin: User = Depends(admin_user)) -> dict:
    async with get_session() as session:
        async def count(stmt) -> int:
            return (await session.execute(stmt)).scalar() or 0

        return {
            "total_users": await count(select(func.count(User.id))),
            "total_jobs": await count(select(func.count(Job.id))),
            "active_jobs": await count(
                select(func.count(Job.id)).where(Job.is_active.is_(True))
            ),
            "total_subscriptions": await count(select(func.count(Subscription.id))),
            "active_subscriptions": await count(
                select(func.count(Subscription.id)).where(
                    Subscription.is_active.is_(True)
                )
            ),
            "total_deliveries": await count(select(func.count(UserJob.id))),
            "total_feedback": await count(
                select(func.count(UserJob.id)).where(UserJob.feedback.isnot(None))
            ),
            "total_applications": await count(select(func.count(Application.id))),
        }


@router.get("/usage")
async def usage(
    days: int = Query(default=30, ge=1, le=90),
    _admin: User = Depends(admin_user),
) -> dict:
    """Daily activity buckets for the last N days (inclusive of today)."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days - 1)
    since = since.replace(hour=0, minute=0, second=0, microsecond=0)

    async with get_session() as session:
        result = await session.execute(
            select(Event.event_type, Event.actor_id, Event.timestamp, Event._payload)
            .where(
                Event.timestamp >= since,
                Event.event_type.in_(("web.pageview", "web.signin", "web.apply_click")),
            )
        )
        rows = result.all()

    buckets: dict[str, dict] = {}
    for offset in range(days):
        day = (since + timedelta(days=offset)).date().isoformat()
        buckets[day] = {
            "date": day, "pageviews": 0, "active_users": set(),
            "signups": 0, "applies": 0,
        }

    import json as _json

    for event_type, actor_id, timestamp, payload_raw in rows:
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        day = timestamp.date().isoformat()
        bucket = buckets.get(day)
        if bucket is None:
            continue
        if event_type == "web.pageview":
            bucket["pageviews"] += 1
        elif event_type == "web.signin":
            try:
                if (_json.loads(payload_raw or "{}")).get("new_user"):
                    bucket["signups"] += 1
            except ValueError:
                pass
        elif event_type == "web.apply_click":
            bucket["applies"] += 1
        if actor_id is not None:
            bucket["active_users"].add(actor_id)

    return {
        "days": [
            {**b, "active_users": len(b["active_users"])}
            for b in buckets.values()
        ]
    }


@router.get("/scrape-health")
async def scrape_health(_admin: User = Depends(admin_user)) -> dict:
    async with get_session() as session:
        by_source = (
            await session.execute(
                select(Job.source, func.count(Job.id))
                .where(Job.is_active.is_(True))
                .group_by(Job.source)
            )
        ).all()

        last_discovered = (
            await session.execute(
                select(func.max(Event.timestamp)).where(
                    Event.event_type == "job.discovered"
                )
            )
        ).scalar()

        recent = (
            await session.execute(
                select(Event)
                .where(Event.event_type.like("job.%"))
                .order_by(Event.timestamp.desc())
                .limit(20)
            )
        ).scalars().all()

    return {
        "jobs_by_source": {source: count for source, count in by_source},
        "last_job_discovered_at": (
            last_discovered.isoformat() if last_discovered else None
        ),
        "recent_events": [
            {
                "event_type": e.event_type,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "job_id": e.job_id,
            }
            for e in recent
        ],
    }
