"""Analytics HTTP adapter — SPA pageview pings."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from gosha.api.deps import optional_user
from gosha.api.schemas import OkOut, PageviewIn
from gosha.models import User
from gosha.services import admin_stats as service

router = APIRouter(prefix="/events", tags=["analytics"])


@router.post("/pageview", response_model=OkOut)
async def pageview(body: PageviewIn, user: User | None = Depends(optional_user)) -> OkOut:
    await service.record_pageview(user.id if user else None, body.path)
    return OkOut()
