"""Application tracker API — the user's Applied list."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select

from gosha.api.deps import ApiError, current_user
from gosha.api.jobs import application_to_out
from gosha.api.schemas import (
    ApplicationCreateIn,
    ApplicationOut,
    ApplicationPatchIn,
    OkOut,
)
from gosha.database import get_session
from gosha.models import APPLICATION_STATUSES, Application, Job, User

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("")
async def list_applications(user: User = Depends(current_user)) -> dict:
    async with get_session() as session:
        result = await session.execute(
            select(Application, Job)
            .join(Job, Application.job_id == Job.id)
            .where(Application.user_id == user.id)
            .order_by(Application.updated_at.desc())
        )
        rows = result.all()
    return {
        "items": [
            application_to_out(app, job).model_dump(mode="json") for app, job in rows
        ]
    }


@router.post("", response_model=ApplicationOut)
async def create_application(
    body: ApplicationCreateIn, user: User = Depends(current_user),
) -> ApplicationOut:
    async with get_session() as session:
        job = await session.get(Job, body.job_id)
        if job is None:
            raise ApiError(404, "not_found", "Job not found.")
        app = (
            await session.execute(
                select(Application).where(
                    Application.user_id == user.id,
                    Application.job_id == body.job_id,
                )
            )
        ).scalar_one_or_none()
        if app is None:
            app = Application(user_id=user.id, job_id=body.job_id, source="web")
            session.add(app)
            await session.commit()
    return application_to_out(app, job)


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
        raise ApiError(404, "not_found", "Application not found.")
    return row[0], row[1]


@router.patch("/{application_id}", response_model=ApplicationOut)
async def update_application(
    application_id: int,
    body: ApplicationPatchIn,
    user: User = Depends(current_user),
) -> ApplicationOut:
    if body.status is not None and body.status not in APPLICATION_STATUSES:
        raise ApiError(
            422,
            "invalid_status",
            f"Status must be one of: {', '.join(APPLICATION_STATUSES)}.",
        )

    app, job = await _own_application(user.id, application_id)
    async with get_session() as session:
        app = await session.merge(app)
        if body.status is not None:
            app.status = body.status
        if body.notes is not None:
            app.notes = body.notes
        app.updated_at = datetime.now(timezone.utc)
        await session.commit()
    return application_to_out(app, job)


@router.delete("/{application_id}", response_model=OkOut)
async def delete_application(
    application_id: int, user: User = Depends(current_user),
) -> OkOut:
    app, _job = await _own_application(user.id, application_id)
    async with get_session() as session:
        app = await session.merge(app)
        await session.delete(app)
        await session.commit()
    return OkOut()
