"""Outbox: Discord messages the web app asks the bot to deliver.

The API process can't talk to the Discord gateway, so it enqueues rows;
the bot polls process_outbox() every ~30s from the scheduler.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from gosha.database import get_session
from gosha.models import Outbox, User

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


async def enqueue(user_id: int, kind: str, payload: dict | None = None) -> Outbox:
    """Queue a message for the bot to DM to a user."""
    async with get_session() as session:
        row = Outbox(
            user_id=user_id,
            kind=kind,
            payload=json.dumps(payload or {}),
        )
        session.add(row)
        await session.commit()
        return row


def _render(kind: str, payload: dict) -> str:
    """Render an outbox row into the DM text the bot sends."""
    if kind == "welcome":
        name = payload.get("search_name") or "your search"
        return (
            f"**Welcome to GOSHA Jobs!** 🎉\n"
            f"I've set up **{name}** — I'll DM you here whenever new "
            f"matching jobs show up.\n"
            f"Manage everything at {payload.get('site_url', 'the website')}."
        )
    if kind == "test_dm":
        return payload.get("text") or "Test message from GOSHA Jobs — DMs work! ✅"
    return payload.get("text", "")


async def process_outbox(bot) -> int:
    """Send pending outbox rows via DM. Returns how many were sent.

    Rows that keep failing are retried on later runs until MAX_ATTEMPTS,
    then skipped (visible in the admin dashboard via last_error).
    """

    async with get_session() as session:
        result = await session.execute(
            select(Outbox, User)
            .join(User, Outbox.user_id == User.id)
            .where(Outbox.sent_at.is_(None), Outbox.attempts < MAX_ATTEMPTS)
            .order_by(Outbox.created_at.asc())
            .limit(50)
        )
        rows = result.all()

    if not rows:
        return 0

    sent = 0
    now = datetime.now(timezone.utc)
    for row, user in rows:
        text = _render(row.kind, row.payload_dict)
        if not text:
            ok, error = True, None  # nothing to send — mark done
        else:
            try:
                ok = await _send_text_dm(bot, user.discord_user_id, text)
                error = None if ok else "DMs closed or user unreachable"
            except Exception as exc:  # bot/network hiccup — retry later
                ok, error = False, str(exc)[:500]

        async with get_session() as session:
            fresh = await session.get(Outbox, row.id)
            if fresh is None:
                continue
            if ok:
                fresh.sent_at = now
                sent += 1
            else:
                fresh.attempts += 1
                fresh.last_error = error
            await session.commit()

    if sent:
        log.info("Outbox: delivered %d message(s)", sent)
    return sent


async def _send_text_dm(bot, discord_id: int, text: str) -> bool:
    """Send a plain-text DM. Returns False when the user can't be reached."""
    import discord as _discord

    try:
        user = bot.get_user(discord_id)
        if user is None:
            user = await bot.fetch_user(discord_id)
        dm = await user.create_dm()
        await dm.send(text)
        return True
    except _discord.Forbidden:
        return False
    except _discord.HTTPException as exc:
        log.warning("Outbox DM to %d failed: %s", discord_id, exc)
        return False
