"""Cover letter listing and generation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

import gosha.cover_letter as cl
from gosha.api.deps import ApiError, current_user
from gosha.database import get_session
from gosha.models import CoverLetter, Job, User

router = APIRouter(tags=["cover-letters"])


@router.get("/cover-letters")
async def list_cover_letters(user: User = Depends(current_user)) -> dict:
    async with get_session() as session:
        result = await session.execute(
            select(CoverLetter, Job)
            .join(Job, CoverLetter.job_id == Job.id)
            .where(CoverLetter.user_id == user.id)
            .order_by(CoverLetter.created_at.desc())
        )
        rows = result.all()
    return {
        "items": [
            {
                "id": letter.id,
                "job_id": job.id,
                "job_title": job.title,
                "company": job.company,
                "content": letter.content,
                "created_at": letter.created_at.isoformat() if letter.created_at else None,
            }
            for letter, job in rows
        ]
    }


@router.post("/jobs/{job_id}/cover-letter")
async def generate_for_job(job_id: int, user: User = Depends(current_user)) -> dict:
    async with get_session() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise ApiError(404, "not_found", "Job not found.")

        cached = (
            await session.execute(
                select(CoverLetter).where(
                    CoverLetter.user_id == user.id, CoverLetter.job_id == job_id
                )
            )
        ).scalar_one_or_none()

    if cl.load_cv(user.id) is None:
        raise ApiError(422, "no_cv", "Upload your CV first so the letter has something to work with.")

    # Cached re-reads don't consume quota; only new generations do.
    if cached is None:
        usage = await cl.get_monthly_usage(user.id)
        limit = int(user.limits["cover_letters_per_month"])
        if usage >= limit:
            raise ApiError(
                403,
                "quota_exceeded",
                f"You've used all {limit} cover letters this month.",
            )

    content, was_cached = await cl.generate_cover_letter(user.id, job_id)
    if content is None:
        raise ApiError(
            502,
            "generation_failed",
            "The AI service is unavailable right now — try again in a bit.",
        )
    return {"content": content, "cached": was_cached}
