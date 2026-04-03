"""Admin dashboard — secured by ADMIN_DISCORD_IDS.

Only Discord users whose ID appears in the ADMIN_DISCORD_IDS env var
can access any /admin/ route. All others get a 403.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select, update

from gosha.database import get_session
from gosha.events import Event
from gosha.models import Job, Subscription, User, UserJob, TIER_LIMITS
from gosha.web.auth import SESSION_SECRET_DEFAULT, SessionManager

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ---------------------------------------------------------------------------
# Admin auth
# ---------------------------------------------------------------------------

_admin_ids_raw = os.getenv("ADMIN_DISCORD_IDS", "")
ADMIN_DISCORD_IDS: set[int] = set()
for _id in _admin_ids_raw.split(","):
    _id = _id.strip()
    if _id.isdigit():
        ADMIN_DISCORD_IDS.add(int(_id))

_session_mgr = SessionManager(
    secret_key=os.getenv("SESSION_SECRET", SESSION_SECRET_DEFAULT),
)


def _get_admin_session(request: Request) -> dict:
    """Validate session and check admin status. Raises 403 if not admin."""
    session_data = _session_mgr.get_session(request.cookies.get("session", ""))
    if not session_data:
        raise HTTPException(status_code=401, detail="Not authenticated. Login at /login first.")
    discord_id = session_data.get("discord_id")
    if discord_id not in ADMIN_DISCORD_IDS:
        raise HTTPException(status_code=403, detail="Access denied. You are not an admin.")
    return session_data


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Admin dashboard page
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    session_data = _get_admin_session(request)
    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "user": session_data,
        "tiers": list(TIER_LIMITS.keys()),
    })


# ---------------------------------------------------------------------------
# API: System stats
# ---------------------------------------------------------------------------


@router.get("/api/stats")
async def admin_stats(request: Request):
    _get_admin_session(request)

    async with get_session() as session:
        total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
        total_jobs = (await session.execute(select(func.count(Job.id)))).scalar() or 0
        active_jobs = (await session.execute(
            select(func.count(Job.id)).where(Job.is_active.is_(True))
        )).scalar() or 0
        total_subs = (await session.execute(select(func.count(Subscription.id)))).scalar() or 0
        active_subs = (await session.execute(
            select(func.count(Subscription.id)).where(Subscription.is_active.is_(True))
        )).scalar() or 0
        total_deliveries = (await session.execute(select(func.count(UserJob.id)))).scalar() or 0
        total_feedback = (await session.execute(
            select(func.count(UserJob.id)).where(UserJob.feedback.isnot(None))
        )).scalar() or 0
        total_events = (await session.execute(select(func.count(Event.id)))).scalar() or 0

        # Tier breakdown
        tier_counts = (await session.execute(
            select(User.tier, func.count(User.id)).group_by(User.tier)
        )).all()

    return {
        "total_users": total_users,
        "total_jobs": total_jobs,
        "active_jobs": active_jobs,
        "total_subscriptions": total_subs,
        "active_subscriptions": active_subs,
        "total_deliveries": total_deliveries,
        "total_feedback": total_feedback,
        "total_events": total_events,
        "tier_breakdown": {tier: count for tier, count in tier_counts},
    }


# ---------------------------------------------------------------------------
# API: Users
# ---------------------------------------------------------------------------


@router.get("/api/users")
async def admin_users(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query(""),
):
    _get_admin_session(request)

    async with get_session() as session:
        base = select(User)
        count_base = select(func.count(User.id))

        if search.strip():
            if search.strip().isdigit():
                base = base.where(User.discord_user_id == int(search.strip()))
                count_base = count_base.where(User.discord_user_id == int(search.strip()))
            else:
                base = base.where(User.tier == search.strip().lower())
                count_base = count_base.where(User.tier == search.strip().lower())

        total = (await session.execute(count_base)).scalar() or 0

        users_result = await session.execute(
            base.order_by(User.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        users = users_result.scalars().all()

        user_data = []
        for u in users:
            sub_count = (await session.execute(
                select(func.count(Subscription.id)).where(Subscription.user_id == u.id)
            )).scalar() or 0
            job_count = (await session.execute(
                select(func.count(UserJob.id)).where(UserJob.user_id == u.id)
            )).scalar() or 0
            user_data.append({
                "id": u.id,
                "discord_user_id": str(u.discord_user_id),
                "tier": u.tier,
                "subscriptions": sub_count,
                "jobs_delivered": job_count,
            })

    return {"users": user_data, "total": total, "page": page, "per_page": per_page}


@router.post("/api/users/{user_id}/tier")
async def admin_set_tier(
    request: Request,
    user_id: int,
    tier: str = Query(...),
):
    _get_admin_session(request)

    if tier not in TIER_LIMITS:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}")

    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        old_tier = user.tier
        user.tier = tier
        await session.commit()

    log.info("Admin changed user %d tier: %s -> %s", user_id, old_tier, tier)
    return {"status": "ok", "user_id": user_id, "old_tier": old_tier, "new_tier": tier}


@router.delete("/api/users/{user_id}")
async def admin_delete_user(request: Request, user_id: int):
    _get_admin_session(request)

    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        await session.delete(user)
        await session.commit()

    log.info("Admin deleted user %d", user_id)
    return {"status": "ok", "user_id": user_id}


# ---------------------------------------------------------------------------
# API: Subscriptions
# ---------------------------------------------------------------------------


@router.get("/api/subscriptions")
async def admin_subscriptions(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user_id: int | None = Query(None),
):
    _get_admin_session(request)

    async with get_session() as session:
        base = select(Subscription, User).join(User)
        count_base = select(func.count(Subscription.id))

        if user_id is not None:
            base = base.where(Subscription.user_id == user_id)
            count_base = count_base.where(Subscription.user_id == user_id)

        total = (await session.execute(count_base)).scalar() or 0
        result = await session.execute(
            base.order_by(Subscription.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        items = result.all()

    subs = []
    for sub, user in items:
        subs.append({
            "id": sub.id,
            "user_id": sub.user_id,
            "discord_user_id": str(user.discord_user_id),
            "keywords": sub.keywords,
            "locations": sub.locations,
            "excluded_keywords": sub.excluded_keywords,
            "company_blacklist": sub.company_blacklist,
            "experience_levels": sub.experience_levels,
            "max_age_days": sub.max_age_days,
            "salary_min": sub.salary_min,
            "is_active": sub.is_active,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        })

    return {"subscriptions": subs, "total": total, "page": page, "per_page": per_page}


@router.post("/api/subscriptions/{sub_id}/toggle")
async def admin_toggle_subscription(request: Request, sub_id: int):
    _get_admin_session(request)

    async with get_session() as session:
        result = await session.execute(select(Subscription).where(Subscription.id == sub_id))
        sub = result.scalar_one_or_none()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")
        sub.is_active = not sub.is_active
        await session.commit()
        new_state = sub.is_active

    log.info("Admin toggled subscription %d -> %s", sub_id, "active" if new_state else "paused")
    return {"status": "ok", "id": sub_id, "is_active": new_state}


@router.delete("/api/subscriptions/{sub_id}")
async def admin_delete_subscription(request: Request, sub_id: int):
    _get_admin_session(request)

    async with get_session() as session:
        result = await session.execute(select(Subscription).where(Subscription.id == sub_id))
        sub = result.scalar_one_or_none()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")
        await session.delete(sub)
        await session.commit()

    log.info("Admin deleted subscription %d", sub_id)
    return {"status": "ok", "id": sub_id}


# ---------------------------------------------------------------------------
# API: Jobs
# ---------------------------------------------------------------------------


@router.get("/api/jobs")
async def admin_jobs(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    source: str = Query(""),
):
    _get_admin_session(request)

    async with get_session() as session:
        base = select(Job)
        count_base = select(func.count(Job.id))

        if search.strip():
            term = f"%{search.strip()}%"
            base = base.where(Job.title.ilike(term) | Job.company.ilike(term))
            count_base = count_base.where(Job.title.ilike(term) | Job.company.ilike(term))

        if source.strip():
            base = base.where(Job.source == source.strip().lower())
            count_base = count_base.where(Job.source == source.strip().lower())

        total = (await session.execute(count_base)).scalar() or 0
        result = await session.execute(
            base.order_by(Job.last_seen_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        jobs = result.scalars().all()

    return {
        "jobs": [
            {
                "id": j.id,
                "title": j.title,
                "company": j.company,
                "location": j.location,
                "url": j.url,
                "source": j.source,
                "salary_min": j.salary_min,
                "salary_max": j.salary_max,
                "salary_currency": j.salary_currency,
                "is_active": j.is_active,
                "first_seen_at": j.first_seen_at.isoformat() if j.first_seen_at else None,
                "last_seen_at": j.last_seen_at.isoformat() if j.last_seen_at else None,
            }
            for j in jobs
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.delete("/api/jobs/{job_id}")
async def admin_delete_job(request: Request, job_id: int):
    _get_admin_session(request)

    async with get_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        await session.delete(job)
        await session.commit()

    log.info("Admin deleted job %d", job_id)
    return {"status": "ok", "id": job_id}


# ---------------------------------------------------------------------------
# API: Events
# ---------------------------------------------------------------------------


@router.get("/api/events")
async def admin_events(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    event_type: str = Query(""),
):
    _get_admin_session(request)

    async with get_session() as session:
        base = select(Event)
        count_base = select(func.count(Event.id))

        if event_type.strip():
            base = base.where(Event.event_type == event_type.strip())
            count_base = count_base.where(Event.event_type == event_type.strip())

        total = (await session.execute(count_base)).scalar() or 0
        result = await session.execute(
            base.order_by(Event.timestamp.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        events = result.scalars().all()

    return {
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "actor_id": e.actor_id,
                "job_id": e.job_id,
                "subscription_id": e.subscription_id,
                "payload": e.payload,
            }
            for e in events
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }
