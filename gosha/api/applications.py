"""Applications HTTP adapter."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from gosha.api.deps import current_user
from gosha.api.jobs import application_to_out
from gosha.api.schemas import (
    ApplicationCreateIn,
    ApplicationOut,
    ApplicationPatchIn,
    OkOut,
)
from gosha.models import User
from gosha.services import applications as service

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("")
async def list_applications(user: User = Depends(current_user)) -> dict:
    rows = await service.list_applications(user.id)
    return {
        "items": [
            application_to_out(app, job).model_dump(mode="json") for app, job in rows
        ]
    }


@router.post("", response_model=ApplicationOut)
async def create_application(
    body: ApplicationCreateIn, user: User = Depends(current_user),
) -> ApplicationOut:
    app, job = await service.create_application(user.id, body.job_id)
    return application_to_out(app, job)


@router.patch("/{application_id}", response_model=ApplicationOut)
async def update_application(
    application_id: int,
    body: ApplicationPatchIn,
    user: User = Depends(current_user),
) -> ApplicationOut:
    app, job = await service.update_application(
        user.id, application_id, status=body.status, notes=body.notes,
    )
    return application_to_out(app, job)


@router.delete("/{application_id}", response_model=OkOut)
async def delete_application(
    application_id: int, user: User = Depends(current_user),
) -> OkOut:
    await service.delete_application(user.id, application_id)
    return OkOut()
