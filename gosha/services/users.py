"""User identity use cases (OAuth upsert lives here; the HTTP dance stays
in the api adapter)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from gosha.database import get_session
from gosha.models import User


async def upsert_discord_user(
    discord_id: int,
    username: str | None,
    avatar_url: str | None,
    in_guild: bool,
) -> tuple[int, bool]:
    """Create or refresh a user after Discord sign-in. Returns (user_id, is_new)."""
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        user = (
            await session.execute(select(User).where(User.discord_user_id == discord_id))
        ).scalar_one_or_none()
        is_new = user is None
        if user is None:
            user = User(discord_user_id=discord_id)
            session.add(user)
        user.username = username
        user.avatar_url = avatar_url
        user.last_login_at = now
        if in_guild:
            user.in_guild = True
        await session.commit()
        return user.id, is_new
