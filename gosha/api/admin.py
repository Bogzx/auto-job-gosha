"""Admin HTTP adapter — stats, usage charts, scrape health. Admin-only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from gosha.api.deps import admin_user
from gosha.models import User
from gosha.services import admin_stats as service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def stats(_admin: User = Depends(admin_user)) -> dict:
    return await service.platform_stats()


@router.get("/usage")
async def usage(
    days: int = Query(default=30, ge=1, le=90),
    _admin: User = Depends(admin_user),
) -> dict:
    return {"days": await service.usage_by_day(days)}


@router.get("/scrape-health")
async def scrape_health(_admin: User = Depends(admin_user)) -> dict:
    return await service.scrape_health()
