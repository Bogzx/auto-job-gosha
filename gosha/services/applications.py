"""Application tracker use cases."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from gosha.database import get_session
from gosha.domain.errors import InvalidStatusError, NotFoundError
from gosha.models import APPLICATION_STATUSES, Application, Job


async def list_applications(user_id: int) -> list[tuple[Application, Job]]:
    async with get_session() as session:
        result = await session.execute(
            select(Application, Job)
            .join(Job, Application.job_id == Job.id)
            .where(Application.user_id == user_id)
            .order_by(Application.updated_at.desc())
        )
        return [(app, job) for app, job in result.all()]


async def create_application(user_id: int, job_id: int) -> tuple[Application, Job]:
    """Idempotent: returns the existing application when already tracked."""
    async with get_session() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise NotFoundError("Job not found.")
        app = (
            await session.execute(
                select(Application).where(
                    Application.user_id == user_id,
                    Application.job_id == job_id,
                )
            )
        ).scalar_one_or_none()
        if app is None:
            app = Application(user_id=user_id, job_id=job_id, source="web")
            session.add(app)
            await session.commit()
    return app, job


async def _own_application(user_id: int, application_id: int) -> tuple[Application, Job]:
    async with get_session() as session:
        row = (
            await session.execute(
                select(Application, Job)
                .join(Job, Application.job_id == Job.id)
                .where(
                    Application.id == application_id,
                    Application.user_id == user_id,
                )
            )
        ).one_or_none()
    if row is None:
        raise NotFoundError("Application not found.")
    return row[0], row[1]


async def update_application(
    user_id: int,
    application_id: int,
    status: str | None = None,
    notes: str | None = None,
) -> tuple[Application, Job]:
    if status is not None and status not in APPLICATION_STATUSES:
        raise InvalidStatusError(
            f"Status must be one of: {', '.join(APPLICATION_STATUSES)}."
        )

    app, job = await _own_application(user_id, application_id)
    async with get_session() as session:
        app = await session.merge(app)
        if status is not None:
            app.status = status
        if notes is not None:
            app.notes = notes
        app.updated_at = datetime.now(timezone.utc)
        await session.commit()
    return app, job


async def delete_application(user_id: int, application_id: int) -> None:
    app, _job = await _own_application(user_id, application_id)
    async with get_session() as session:
        app = await session.merge(app)
        await session.delete(app)
        await session.commit()
