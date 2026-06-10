"""CV HTTP adapter."""

from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile

from gosha.api.deps import current_user
from gosha.api.schemas import OkOut
from gosha.models import User
from gosha.services import cv as service

router = APIRouter(prefix="/cv", tags=["cv"])


@router.get("")
async def get_cv(user: User = Depends(current_user)) -> dict:
    return service.get_cv(user.id)


@router.put("")
async def upload_cv(file: UploadFile, user: User = Depends(current_user)) -> dict:
    content = await file.read()
    return await service.upload_cv(user.id, file.filename or "cv", content)


@router.delete("", response_model=OkOut)
async def delete_cv(user: User = Depends(current_user)) -> OkOut:
    await service.delete_cv(user.id)
    return OkOut()
