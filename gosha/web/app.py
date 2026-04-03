"""FastAPI web dashboard application.

Provides:
  - Discord OAuth2 login
  - Job feed (browse all matched jobs)
  - Subscription management (CRUD)
  - Analytics (delivery stats, feedback breakdown)
  - Job status tracking (applied, interviewing, rejected)
"""

from __future__ import annotations

import hmac
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from starlette.middleware.base import BaseHTTPMiddleware

from gosha.database import get_session
from gosha.models import Job, Subscription, User, UserJob
from gosha.web.auth import (
    IS_PRODUCTION,
    SESSION_SECRET_DEFAULT,
    SessionManager,
    _check_session_secret,
    oauth2_callback_handler,
    oauth2_login_url,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        return response


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Ensure DB is initialised when running the web app standalone."""
    from gosha.database import _engine, init_db

    _check_session_secret()

    if _engine is None:
        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/jobs.db")
        await init_db(db_url)
    yield


app = FastAPI(title="GOSHA Dashboard", version="1.0.0", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

session_mgr = SessionManager(
    secret_key=os.getenv("SESSION_SECRET", SESSION_SECRET_DEFAULT),
)

# Mount admin router
from gosha.web.admin import router as admin_router  # noqa: E402
app.include_router(admin_router)


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@app.get("/login")
async def login(request: Request):
    """Redirect to Discord OAuth2 with CSRF state."""
    url, state = oauth2_login_url()
    if not url:
        return JSONResponse(
            {"error": "Discord OAuth2 not configured. Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET."},
            status_code=500,
        )
    response = RedirectResponse(url)
    # Store state in a short-lived cookie for verification in callback
    response.set_cookie(
        "oauth_state", state, httponly=True, max_age=300,
        secure=IS_PRODUCTION, samesite="lax",
    )
    return response


@app.get("/callback")
async def callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(""),
):
    """Handle Discord OAuth2 callback with CSRF state verification."""
    # Verify OAuth2 state to prevent CSRF
    expected_state = request.cookies.get("oauth_state", "")
    if not expected_state or not state or not hmac.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Invalid or missing OAuth2 state")

    user_data = await oauth2_callback_handler(code)
    if not user_data:
        raise HTTPException(status_code=401, detail="OAuth2 authentication failed")

    discord_id = int(user_data["id"])
    username = user_data.get("username", "Unknown")

    # Ensure user exists in DB
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.discord_user_id == discord_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(discord_user_id=discord_id)
            session.add(user)
            await session.commit()

    # Create session
    token = session_mgr.create_session(discord_id, username)
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(
        "session",
        token,
        httponly=True,
        max_age=86400 * 7,
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
    )
    # Clean up the OAuth state cookie
    response.delete_cookie("oauth_state")
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("session", path="/")
    return response


# ---------------------------------------------------------------------------
# Dashboard pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    session_data = session_mgr.get_session(request.cookies.get("session", ""))
    return templates.TemplateResponse(request, "index.html", {
        "user": session_data,
    })


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    session_data = session_mgr.get_session(request.cookies.get("session", ""))
    if not session_data:
        return RedirectResponse("/login")

    discord_id = session_data["discord_id"]

    async with get_session() as session:
        # Get user
        user_result = await session.execute(
            select(User).where(User.discord_user_id == discord_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return RedirectResponse("/login")

        # Stats
        total_delivered = await session.execute(
            select(func.count(UserJob.id)).where(UserJob.user_id == user.id)
        )
        interested_count = await session.execute(
            select(func.count(UserJob.id)).where(
                UserJob.user_id == user.id, UserJob.feedback == "interested"
            )
        )
        not_relevant_count = await session.execute(
            select(func.count(UserJob.id)).where(
                UserJob.user_id == user.id, UserJob.feedback == "not_relevant"
            )
        )
        sub_count = await session.execute(
            select(func.count(Subscription.id)).where(
                Subscription.user_id == user.id, Subscription.is_active == True
            )
        )

    stats = {
        "total_delivered": total_delivered.scalar() or 0,
        "interested": interested_count.scalar() or 0,
        "not_relevant": not_relevant_count.scalar() or 0,
        "active_subscriptions": sub_count.scalar() or 0,
    }

    return templates.TemplateResponse(request, "dashboard.html", {
        "user": session_data,
        "stats": stats,
    })


# ---------------------------------------------------------------------------
# API routes (JSON — used by HTMX or SPA)
# ---------------------------------------------------------------------------


@app.get("/api/jobs")
async def api_jobs(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Get paginated job feed for the current user."""
    session_data = session_mgr.get_session(request.cookies.get("session", ""))
    if not session_data:
        raise HTTPException(status_code=401)

    discord_id = session_data["discord_id"]

    async with get_session() as session:
        user_result = await session.execute(
            select(User).where(User.discord_user_id == discord_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404)

        offset = (page - 1) * per_page
        result = await session.execute(
            select(UserJob, Job)
            .join(Job, UserJob.job_id == Job.id)
            .where(UserJob.user_id == user.id)
            .order_by(UserJob.delivered_at.desc())
            .offset(offset)
            .limit(per_page)
        )
        items = result.all()

        total_result = await session.execute(
            select(func.count(UserJob.id)).where(UserJob.user_id == user.id)
        )
        total = total_result.scalar() or 0

    jobs = [
        {
            "id": uj.id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "url": job.url,
            "source": job.source,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "salary_currency": job.salary_currency,
            "score": uj.relevance_score,
            "feedback": uj.feedback,
            "delivered_at": uj.delivered_at.isoformat() if uj.delivered_at else None,
        }
        for uj, job in items
    ]

    return {
        "jobs": jobs,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page,
    }


@app.get("/api/subscriptions")
async def api_subscriptions(request: Request):
    """Get all subscriptions for the current user."""
    session_data = session_mgr.get_session(request.cookies.get("session", ""))
    if not session_data:
        raise HTTPException(status_code=401)

    discord_id = session_data["discord_id"]

    async with get_session() as session:
        user_result = await session.execute(
            select(User).where(User.discord_user_id == discord_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404)

        result = await session.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subs = result.scalars().all()

    return [
        {
            "id": s.id,
            "keywords": s.keywords,
            "locations": s.locations,
            "excluded_keywords": s.excluded_keywords,
            "company_blacklist": s.company_blacklist,
            "experience_levels": s.experience_levels,
            "salary_min": s.salary_min,
            "max_age_days": s.max_age_days,
            "is_active": s.is_active,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in subs
    ]


@app.post("/api/feedback/{user_job_id}")
async def api_feedback(
    request: Request,
    user_job_id: int,
    feedback: str = Query(..., pattern="^(interested|not_relevant)$"),
):
    """Record feedback on a delivered job."""
    session_data = session_mgr.get_session(request.cookies.get("session", ""))
    if not session_data:
        raise HTTPException(status_code=401)

    discord_id = session_data["discord_id"]

    # Verify the UserJob belongs to the requesting user
    async with get_session() as session:
        user_result = await session.execute(
            select(User).where(User.discord_user_id == discord_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404)

        uj_result = await session.execute(
            select(UserJob).where(
                UserJob.id == user_job_id,
                UserJob.user_id == user.id,
            )
        )
        if uj_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404)

    from gosha.feedback import record_feedback

    success = await record_feedback(user_job_id, feedback)
    if not success:
        raise HTTPException(status_code=500)
    return {"status": "ok", "feedback": feedback}


@app.get("/api/stats")
async def api_stats(request: Request):
    """Get delivery statistics."""
    session_data = session_mgr.get_session(request.cookies.get("session", ""))
    if not session_data:
        raise HTTPException(status_code=401)

    discord_id = session_data["discord_id"]

    async with get_session() as session:
        user_result = await session.execute(
            select(User).where(User.discord_user_id == discord_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404)

        # Aggregate stats
        total = await session.execute(
            select(func.count(UserJob.id)).where(UserJob.user_id == user.id)
        )
        interested = await session.execute(
            select(func.count(UserJob.id)).where(
                UserJob.user_id == user.id, UserJob.feedback == "interested"
            )
        )
        not_relevant = await session.execute(
            select(func.count(UserJob.id)).where(
                UserJob.user_id == user.id, UserJob.feedback == "not_relevant"
            )
        )

        # Top companies
        top_companies = await session.execute(
            select(Job.company, func.count(UserJob.id))
            .join(UserJob, UserJob.job_id == Job.id)
            .where(UserJob.user_id == user.id)
            .group_by(Job.company)
            .order_by(func.count(UserJob.id).desc())
            .limit(10)
        )

        # Top sources
        top_sources = await session.execute(
            select(Job.source, func.count(UserJob.id))
            .join(UserJob, UserJob.job_id == Job.id)
            .where(UserJob.user_id == user.id)
            .group_by(Job.source)
            .order_by(func.count(UserJob.id).desc())
        )

    return {
        "total_delivered": total.scalar() or 0,
        "interested": interested.scalar() or 0,
        "not_relevant": not_relevant.scalar() or 0,
        "top_companies": [
            {"company": c, "count": n} for c, n in top_companies.all()
        ],
        "top_sources": [
            {"source": s, "count": n} for s, n in top_sources.all()
        ],
    }
