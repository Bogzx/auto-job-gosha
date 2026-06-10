"""Privacy-friendly usage tracking: SPA pageview pings into the events table.

No third-party trackers, no extra cookies — anonymous views are counted
without any identity, signed-in views attach the user id so the admin
dashboard can chart daily active users.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from gosha.api.deps import optional_user
from gosha.api.schemas import OkOut, PageviewIn
from gosha.models import User

router = APIRouter(prefix="/events", tags=["analytics"])


@router.post("/pageview", response_model=OkOut)
async def pageview(body: PageviewIn, user: User | None = Depends(optional_user)) -> OkOut:
    try:
        from gosha.events import get_event_store
        await get_event_store().emit(
            "web.pageview",
            actor_id=user.id if user else None,
            payload={"path": body.path[:200]},
        )
    except Exception:
        pass  # analytics must never break the site
    return OkOut()
