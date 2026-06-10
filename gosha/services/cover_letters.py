"""Cover letter use cases: listing and quota-guarded generation."""

from __future__ import annotations

from sqlalchemy import select

import gosha.cover_letter as cl
from gosha.database import get_session
from gosha.domain.errors import (
    GenerationFailedError,
    NoCvError,
    NotFoundError,
    QuotaExceededError,
)
from gosha.models import CoverLetter, Job, User


async def list_cover_letters(user_id: int) -> list[tuple[CoverLetter, Job]]:
    async with get_session() as session:
        result = await session.execute(
            select(CoverLetter, Job)
            .join(Job, CoverLetter.job_id == Job.id)
            .where(CoverLetter.user_id == user_id)
            .order_by(CoverLetter.created_at.desc())
        )
        return [(letter, job) for letter, job in result.all()]


async def generate_for_job(user: User, job_id: int) -> tuple[str, bool]:
    """Returns (content, was_cached). Cached re-reads don't consume quota."""
    async with get_session() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise NotFoundError("Job not found.")

        cached = (
            await session.execute(
                select(CoverLetter).where(
                    CoverLetter.user_id == user.id, CoverLetter.job_id == job_id
                )
            )
        ).scalar_one_or_none()

    if cl.load_cv(user.id) is None:
        raise NoCvError("Upload your CV first so the letter has something to work with.")

    if cached is None:
        usage = await cl.get_monthly_usage(user.id)
        limit = int(user.limits["cover_letters_per_month"])
        if usage >= limit:
            raise QuotaExceededError(
                f"You've used all {limit} cover letters this month."
            )

    content, was_cached = await cl.generate_cover_letter(user.id, job_id)
    if content is None:
        raise GenerationFailedError(
            "The AI service is unavailable right now — try again in a bit."
        )
    return content, was_cached
