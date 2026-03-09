"""Scheduled background task that scrapes jobs and notifies subscribers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from sqlalchemy import select

from database import SeenJob, Subscription, User, get_session
from scraper import search_jobs

if TYPE_CHECKING:
    from bot import JobBot
    from ssh_tunnels import SSHTunnelManager

log = logging.getLogger(__name__)


async def _dm_user(bot: JobBot, discord_id: int, embed: discord.Embed) -> None:
    """Send an embed to a user via DM. Silently skip if DMs are closed."""
    try:
        user = bot.get_user(discord_id)
        if user is None:
            user = await bot.fetch_user(discord_id)
        dm = await user.create_dm()
        await dm.send(embed=embed)
    except discord.Forbidden:
        log.warning("Cannot DM user %d – DMs are closed", discord_id)
    except discord.HTTPException as exc:
        log.error("Failed to DM user %d: %s", discord_id, exc)


async def run_scrape_cycle(
    bot: JobBot,
    tunnel_manager: SSHTunnelManager,
    alert_channel_id: int,
) -> None:
    """Execute one full scrape-and-notify cycle.

    1. Collect distinct (keyword, location, max_age_days) combos.
    2. Scrape each combo once.
    3. Deduplicate against SeenJob per user.
    4. DM each user their new jobs privately.
    5. Post a summary to the alert channel (if configured).
    """
    log.info("=== Scrape cycle started ===")

    # ── 1. Gather unique search combos & map to subscribers ─────
    async with get_session() as session:
        result = await session.execute(select(Subscription))
        all_subs = result.scalars().all()

    if not all_subs:
        log.info("No subscriptions – nothing to scrape.")
        return

    # Build combo → list of (internal_user_id, discord_user_id)
    combo_map: dict[tuple[str, str, int], list[tuple[int, int]]] = {}

    async with get_session() as session:
        for sub in all_subs:
            user = await session.get(User, sub.user_id)
            if user is None:
                continue
            key = (sub.keyword.lower(), sub.location.lower(), sub.max_age_days)
            combo_map.setdefault(key, []).append((user.id, user.discord_user_id))

    # ── 2. Scrape each combo once ──────────────────────────────
    total_new = 0

    for (keyword, location, max_age_days), user_pairs in combo_map.items():
        df = await search_jobs(tunnel_manager, keyword, location, max_age_days)
        if df.empty:
            continue

        # Deduplicate user list (same user might have overlapping subs)
        unique_users = list({uid: (uid, did) for uid, did in user_pairs}.values())

        # ── 3. Filter & notify per user ────────────────────────
        for _, row in df.iterrows():
            job_url = str(row.get("job_url") or row.get("job_url_direct") or row.get("link") or "")
            if not job_url or job_url == "nan":
                continue

            title = str(row.get("title", "Unknown Title"))
            company = str(row.get("company", "Unknown"))
            job_location = str(row.get("location", location))
            description = str(row.get("description") or "")
            # Truncate description for embed
            if description in ("", "nan", "None"):
                description = ""
            elif len(description) > 200:
                description = description[:200] + "…"

            embed = discord.Embed(
                title=title,
                url=job_url,
                color=discord.Color.green(),
            )
            embed.add_field(name="Company", value=company, inline=True)
            embed.add_field(name="Location", value=job_location, inline=True)
            embed.add_field(name="Search", value=keyword, inline=True)
            if description and description != "nan":
                embed.add_field(name="Description", value=description, inline=False)

            async with get_session() as session:
                for internal_uid, discord_uid in unique_users:
                    # Check if already seen
                    seen_result = await session.execute(
                        select(SeenJob).where(
                            SeenJob.user_id == internal_uid,
                            SeenJob.job_url == job_url,
                        )
                    )
                    if seen_result.scalar_one_or_none() is not None:
                        continue

                    # Mark as seen
                    session.add(SeenJob(user_id=internal_uid, job_url=job_url))
                    await session.commit()

                    # DM the user
                    await _dm_user(bot, discord_uid, embed)
                    total_new += 1

    # ── 5. Optional: post summary to alert channel ─────────────
    if alert_channel_id and total_new > 0:
        channel = bot.get_channel(alert_channel_id)
        if channel is not None:
            try:
                await channel.send(f"📬 Scrape complete — sent **{total_new}** new job alerts via DM.")  # type: ignore[union-attr]
            except discord.HTTPException:
                pass

    log.info("=== Scrape cycle finished — %d new jobs sent ===", total_new)
