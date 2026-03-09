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


async def run_scrape_cycle(
    bot: JobBot,
    tunnel_manager: SSHTunnelManager,
    alert_channel_id: int,
) -> None:
    """Execute one full scrape-and-notify cycle.

    1. Collect distinct (keyword, location, max_age_days) combos.
    2. Scrape each combo once.
    3. Deduplicate against SeenJob.
    4. Send Discord embeds tagging the relevant users.
    """
    log.info("=== Scrape cycle started ===")

    # ── 1. Gather unique search combos & map to subscribers ─────
    async with get_session() as session:
        result = await session.execute(
            select(Subscription).options()  # subscriptions already eager-load user
        )
        all_subs = result.scalars().all()

    if not all_subs:
        log.info("No subscriptions – nothing to scrape.")
        return

    # combo → list of discord_user_ids
    combo_map: dict[tuple[str, str, int], list[int]] = {}
    # subscription also carries user.discord_user_id via relationship
    sub_user_discord_ids: dict[int, int] = {}  # sub.user_id → discord id

    async with get_session() as session:
        for sub in all_subs:
            user = await session.get(User, sub.user_id)
            if user is None:
                continue
            sub_user_discord_ids[sub.user_id] = user.discord_user_id
            key = (sub.keyword.lower(), sub.location.lower(), sub.max_age_days)
            combo_map.setdefault(key, []).append(user.discord_user_id)

    # ── 2. Scrape each combo once ──────────────────────────────
    channel: discord.abc.Messageable | None = None
    if alert_channel_id:
        channel = bot.get_channel(alert_channel_id)  # type: ignore[assignment]

    for (keyword, location, max_age_days), discord_ids in combo_map.items():
        df = await search_jobs(tunnel_manager, keyword, location, max_age_days)
        if df.empty:
            continue

        unique_discord_ids = list(set(discord_ids))

        # ── 3. Filter out already-seen jobs per user ───────────
        for _, row in df.iterrows():
            job_url = str(row.get("job_url") or row.get("job_url_direct") or row.get("link") or "")
            if not job_url or job_url == "nan":
                continue

            title = str(row.get("title", "Unknown Title"))
            company = str(row.get("company", "Unknown"))
            job_location = str(row.get("location", location))

            notified_users: list[int] = []

            async with get_session() as session:
                for uid in unique_discord_ids:
                    # Resolve internal user id
                    u_result = await session.execute(
                        select(User).where(User.discord_user_id == uid)
                    )
                    user = u_result.scalar_one_or_none()
                    if user is None:
                        continue

                    # Check if already seen
                    seen_result = await session.execute(
                        select(SeenJob).where(
                            SeenJob.user_id == user.id,
                            SeenJob.job_url == job_url,
                        )
                    )
                    if seen_result.scalar_one_or_none() is not None:
                        continue

                    # Mark as seen
                    session.add(SeenJob(user_id=user.id, job_url=job_url))
                    notified_users.append(uid)

                await session.commit()

            if not notified_users:
                continue

            # ── 4. Send styled embed ───────────────────────────
            mentions = " ".join(f"<@{uid}>" for uid in notified_users)
            embed = discord.Embed(
                title=title,
                url=job_url,
                color=discord.Color.green(),
            )
            embed.add_field(name="Company", value=company, inline=True)
            embed.add_field(name="Location", value=job_location, inline=True)
            embed.add_field(name="Search", value=f"{keyword}", inline=False)

            target = channel
            if target is None:
                # Fall back: DM the first user (useful during dev)
                for uid in notified_users:
                    dm_user = bot.get_user(uid)
                    if dm_user:
                        target = await dm_user.create_dm()
                        break

            if target is not None:
                try:
                    await target.send(content=mentions, embed=embed)
                except discord.HTTPException as exc:
                    log.error("Failed to send alert: %s", exc)

    log.info("=== Scrape cycle finished ===")
