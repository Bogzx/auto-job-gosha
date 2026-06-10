"""Jobs browsing API: list with filters, detail, feedback, apply-click."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select

from gosha.api.deps import ApiError, current_user
from gosha.api.schemas import (
    ApplicationOut,
    FeedbackIn,
    JobListOut,
    JobOut,
    JobSummaryOut,
    OkOut,
)
from gosha.database import get_session
from gosha.filters import (
    location_matches,
    matches_experience_level,
    normalize_location,
)
from gosha.models import Application, Job, User, UserJob

log = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

LIST_DESCRIPTION_CHARS = 240
MAX_CANDIDATES = 2000


def job_to_out(
    job: Job,
    *,
    truncate: bool = True,
    feedback: str | None = None,
    applied: bool = False,
    match_score: float | None = None,
    match_reasons: list[str] | None = None,
) -> JobOut:
    description = job.description
    if truncate and description and len(description) > LIST_DESCRIPTION_CHARS:
        description = description[:LIST_DESCRIPTION_CHARS] + "…"
    return JobOut(
        id=job.id,
        url=job.url,
        title=job.title,
        company=job.company,
        location=job.location,
        description=description,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        source=job.source,
        posted_at=job.posted_at,
        first_seen_at=job.first_seen_at,
        match_score=match_score,
        match_reasons=match_reasons,
        feedback=feedback,
        applied=applied,
    )


async def annotate_user_state(
    user_id: int, job_ids: list[int],
) -> tuple[dict[int, str], set[int]]:
    """Return ({job_id: feedback}, {applied job_ids}) for the given jobs."""
    if not job_ids:
        return {}, set()
    async with get_session() as session:
        fb_rows = await session.execute(
            select(UserJob.job_id, UserJob.feedback).where(
                UserJob.user_id == user_id,
                UserJob.job_id.in_(job_ids),
                UserJob.feedback.isnot(None),
            )
        )
        feedback = {job_id: fb for job_id, fb in fb_rows.all()}
        app_rows = await session.execute(
            select(Application.job_id).where(
                Application.user_id == user_id, Application.job_id.in_(job_ids)
            )
        )
        applied = {row[0] for row in app_rows.all()}
    return feedback, applied


@router.get("", response_model=JobListOut)
async def list_jobs(
    user: User = Depends(current_user),
    q: str = "",
    locations: str = "",
    experience: str = "",
    sources: str = "",
    salary_min: int | None = None,
    posted_within_days: int | None = Query(default=None, ge=1, le=90),
    remote: bool = False,
    sort: str = Query(default="date", pattern="^(date|match)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
) -> JobListOut:
    stmt = select(Job).where(Job.is_active.is_(True))

    if q.strip():
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(Job.title.ilike(needle), Job.company.ilike(needle)))
    if sources.strip():
        wanted = [s.strip().lower() for s in sources.split(",") if s.strip()]
        stmt = stmt.where(Job.source.in_(wanted))
    if salary_min is not None:
        stmt = stmt.where(
            or_(
                Job.salary_max >= salary_min,
                Job.salary_min >= salary_min,
                # No salary data — benefit of the doubt (mirrors matching logic)
                Job.salary_min.is_(None) & Job.salary_max.is_(None),
            )
        )
    if posted_within_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=posted_within_days)
        stmt = stmt.where(Job.first_seen_at >= cutoff)

    stmt = stmt.order_by(Job.first_seen_at.desc()).limit(MAX_CANDIDATES)

    async with get_session() as session:
        result = await session.execute(stmt)
        candidates = list(result.scalars().all())

    # Location + experience filters need the alias/regex helpers (post-SQL)
    location_list = [loc.strip() for loc in locations.split(",") if loc.strip()]
    if location_list or remote:
        match_subs: list[str] = []
        for loc in location_list:
            _search, subs = normalize_location(loc)
            match_subs.extend(subs)
        if remote:
            _search, remote_subs = normalize_location("remote")
            match_subs.extend(remote_subs)
        candidates = [
            j for j in candidates if location_matches(j.location, match_subs)
        ]

    experience_list = [e.strip().lower() for e in experience.split(",") if e.strip()]
    if experience_list:
        candidates = [
            j for j in candidates if matches_experience_level(j.title, experience_list)
        ]

    total = len(candidates)
    start = (page - 1) * per_page
    page_jobs = candidates[start : start + per_page]

    feedback, applied = await annotate_user_state(user.id, [j.id for j in page_jobs])
    items = [
        job_to_out(
            j,
            feedback=feedback.get(j.id),
            applied=j.id in applied,
        )
        for j in page_jobs
    ]
    return JobListOut(items=items, total=total, page=page, per_page=per_page)


async def _get_job_or_404(job_id: int) -> Job:
    async with get_session() as session:
        job = await session.get(Job, job_id)
    if job is None:
        raise ApiError(404, "not_found", "Job not found.")
    return job


@router.get("/{job_id}", response_model=JobOut)
async def job_detail(job_id: int, user: User = Depends(current_user)) -> JobOut:
    job = await _get_job_or_404(job_id)
    feedback, applied = await annotate_user_state(user.id, [job.id])
    return job_to_out(
        job,
        truncate=False,
        feedback=feedback.get(job.id),
        applied=job.id in applied,
    )


@router.post("/{job_id}/feedback", response_model=OkOut)
async def job_feedback(
    job_id: int, body: FeedbackIn, user: User = Depends(current_user),
) -> OkOut:
    await _get_job_or_404(job_id)
    now = datetime.now(timezone.utc)

    async with get_session() as session:
        uj = (
            await session.execute(
                select(UserJob).where(
                    UserJob.user_id == user.id, UserJob.job_id == job_id
                )
            )
        ).scalar_one_or_none()
        if uj is None:
            # Web users rate jobs they were never DMed about
            uj = UserJob(user_id=user.id, job_id=job_id)
            session.add(uj)
        uj.feedback = body.feedback
        uj.feedback_at = now
        await session.commit()

    try:
        from gosha.events import emit_user_feedback
        await emit_user_feedback(job_id, user.id, body.feedback)
    except Exception:
        pass
    return OkOut()


def application_to_out(app: Application, job: Job) -> ApplicationOut:
    return ApplicationOut(
        id=app.id,
        job_id=app.job_id,
        status=app.status,
        notes=app.notes,
        applied_at=app.applied_at,
        updated_at=app.updated_at,
        source=app.source,
        job=JobSummaryOut(
            id=job.id,
            title=job.title,
            company=job.company,
            location=job.location,
            url=job.url,
            source=job.source,
        ),
    )


@router.post("/{job_id}/apply-click", response_model=ApplicationOut)
async def apply_click(job_id: int, user: User = Depends(current_user)) -> ApplicationOut:
    """Record that the user clicked Apply — auto-tracks the application."""
    job = await _get_job_or_404(job_id)

    async with get_session() as session:
        app = (
            await session.execute(
                select(Application).where(
                    Application.user_id == user.id, Application.job_id == job_id
                )
            )
        ).scalar_one_or_none()
        created = app is None
        if app is None:
            app = Application(user_id=user.id, job_id=job_id, source="web")
            session.add(app)
            await session.commit()

    if created:
        try:
            from gosha.events import get_event_store
            await get_event_store().emit(
                "web.apply_click", actor_id=user.id, job_id=job_id
            )
        except Exception:
            pass

    return application_to_out(app, job)
