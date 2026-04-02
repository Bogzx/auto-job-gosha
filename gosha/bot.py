"""Discord slash-command handlers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from gosha.database import get_session
from gosha.models import Subscription, User

if TYPE_CHECKING:
    from gosha.config import Settings
    from gosha.ssh_tunnels import SSHTunnelManager

log = logging.getLogger(__name__)


class JobBot(commands.Bot):
    """Custom Bot subclass — syncs command tree on ready."""

    tunnel_manager: SSHTunnelManager | None = None
    alert_channel_id: int = 0
    settings: Settings | None = None  # Set by main.py

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        # Register interaction handler so feedback buttons
        # work even after bot restart
        from gosha.views import setup_interaction_handler
        setup_interaction_handler(self)

        await self.add_cog(SubscriptionCog(self))
        await self.tree.sync()
        log.info("Slash commands synced")

        @self.tree.error
        async def on_app_command_error(
            interaction: discord.Interaction, error: app_commands.AppCommandError
        ) -> None:
            log.exception("Slash command error: %s", error)
            msg = f"Something went wrong: {error}"
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except discord.HTTPException:
                pass


class SubscriptionCog(commands.Cog):
    """Slash commands for managing job-search subscriptions."""

    def __init__(self, bot: JobBot) -> None:
        self.bot = bot

    # ── helpers ──────────────────────────────────────────────────

    async def _get_or_create_user(self, session: Any, discord_id: int) -> User:
        result = await session.execute(
            select(User).where(User.discord_user_id == discord_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(discord_user_id=discord_id)
            session.add(user)
            await session.flush()
        return user

    # ── /subscribe ──────────────────────────────────────────────

    @app_commands.command(
        name="subscribe",
        description="Add a new job-search subscription",
    )
    @app_commands.describe(
        keyword="Search term(s), comma-separated. e.g. 'software engineer, backend developer'",
        location="Location(s), comma-separated. e.g. 'Cluj, Bucharest'",
        max_age_days="Only show jobs posted within this many days (default 7)",
        experience="Experience level: intern, junior, mid, senior, any (default any)",
        exclude="Keywords to exclude, comma-separated. e.g. 'sales, marketing'",
        salary_min="Minimum salary (annual, in local currency)",
    )
    async def subscribe(
        self,
        interaction: discord.Interaction,
        keyword: str,
        location: str,
        max_age_days: int = 7,
        experience: str = "any",
        exclude: str = "",
        salary_min: int | None = None,
    ) -> None:
        try:
            keywords = [k.strip() for k in keyword.split(",") if k.strip()]
            locations = [loc.strip() for loc in location.split(",") if loc.strip()]
            excluded = [e.strip() for e in exclude.split(",") if e.strip()] if exclude else []
            exp_levels = [e.strip().lower() for e in experience.split(",") if e.strip()]

            if not keywords or not locations:
                await interaction.response.send_message(
                    "Please provide at least one keyword and one location.",
                    ephemeral=True,
                )
                return

            async with get_session() as session:
                user = await self._get_or_create_user(session, interaction.user.id)

                sub = Subscription(
                    user_id=user.id,
                    max_age_days=max_age_days,
                    salary_min=salary_min,
                )
                sub.keywords = keywords
                sub.locations = locations
                sub.excluded_keywords = excluded
                sub.experience_levels = exp_levels
                session.add(sub)
                await session.commit()

                # Emit event
                try:
                    from gosha.events import emit_subscription_created
                    await emit_subscription_created(user.id, sub.id, keywords)
                except Exception:
                    pass  # Events are best-effort

                kw_display = ", ".join(keywords)
                loc_display = ", ".join(locations)
                await interaction.response.send_message(
                    f"Subscribed! **#{sub.id}** — `{kw_display}` in `{loc_display}` "
                    f"(last {max_age_days}d, experience: {experience})",
                    ephemeral=True,
                )
        except Exception as exc:
            log.exception("Error in /subscribe")
            msg = f"Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)

    # ── /unsubscribe ────────────────────────────────────────────

    @app_commands.command(
        name="unsubscribe",
        description="Remove one of your subscriptions by ID",
    )
    @app_commands.describe(id="Subscription ID shown by /my_searches")
    async def unsubscribe(self, interaction: discord.Interaction, id: int) -> None:
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Subscription)
                    .join(User)
                    .where(
                        Subscription.id == id,
                        User.discord_user_id == interaction.user.id,
                    )
                )
                sub = result.scalar_one_or_none()
                if sub is None:
                    await interaction.response.send_message(
                        "Subscription not found or you don't own it.",
                        ephemeral=True,
                    )
                    return

                user_id = sub.user_id
                await session.delete(sub)
                await session.commit()

                try:
                    from gosha.events import emit_subscription_deleted
                    await emit_subscription_deleted(user_id, id)
                except Exception:
                    pass

                await interaction.response.send_message(
                    f"Subscription **#{id}** removed.", ephemeral=True
                )
        except Exception as exc:
            log.exception("Error in /unsubscribe")
            msg = f"Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)

    # ── /edit ───────────────────────────────────────────────────

    @app_commands.command(
        name="edit",
        description="Edit an existing subscription",
    )
    @app_commands.describe(
        id="Subscription ID to edit",
        keyword="New keyword(s), comma-separated (leave blank to keep)",
        location="New location(s), comma-separated (leave blank to keep)",
        max_age_days="New max age in days (0 to keep current)",
        experience="New experience level (leave blank to keep)",
        exclude="New exclusions, comma-separated (leave blank to keep)",
        blacklist="Blacklisted companies, comma-separated (leave blank to keep)",
        salary_min="New minimum salary (0 to remove, -1 to keep)",
    )
    async def edit(
        self,
        interaction: discord.Interaction,
        id: int,
        keyword: str = "",
        location: str = "",
        max_age_days: int = 0,
        experience: str = "",
        exclude: str = "",
        blacklist: str = "",
        salary_min: int = -1,
    ) -> None:
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Subscription)
                    .join(User)
                    .where(
                        Subscription.id == id,
                        User.discord_user_id == interaction.user.id,
                    )
                )
                sub = result.scalar_one_or_none()
                if sub is None:
                    await interaction.response.send_message(
                        "Subscription not found or you don't own it.",
                        ephemeral=True,
                    )
                    return

                changes = []
                if keyword:
                    sub.keywords = [k.strip() for k in keyword.split(",") if k.strip()]
                    changes.append(f"keywords={sub.keywords}")
                if location:
                    sub.locations = [loc.strip() for loc in location.split(",") if loc.strip()]
                    changes.append(f"locations={sub.locations}")
                if max_age_days > 0:
                    sub.max_age_days = max_age_days
                    changes.append(f"max_age_days={max_age_days}")
                if experience:
                    sub.experience_levels = [e.strip().lower() for e in experience.split(",") if e.strip()]
                    changes.append(f"experience={sub.experience_levels}")
                if exclude:
                    sub.excluded_keywords = [e.strip() for e in exclude.split(",") if e.strip()]
                    changes.append(f"excluded={sub.excluded_keywords}")
                if blacklist:
                    sub.company_blacklist = [b.strip() for b in blacklist.split(",") if b.strip()]
                    changes.append(f"blacklist={sub.company_blacklist}")
                if salary_min == 0:
                    sub.salary_min = None
                    changes.append("salary_min=removed")
                elif salary_min > 0:
                    sub.salary_min = salary_min
                    changes.append(f"salary_min={salary_min}")

                if not changes:
                    await interaction.response.send_message(
                        "No changes specified.", ephemeral=True
                    )
                    return

                await session.commit()
                await interaction.response.send_message(
                    f"Updated **#{id}**: {', '.join(changes)}",
                    ephemeral=True,
                )
        except Exception as exc:
            log.exception("Error in /edit")
            msg = f"Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)

    # ── /pause & /resume ────────────────────────────────────────

    @app_commands.command(
        name="pause", description="Pause a subscription (stop receiving jobs)"
    )
    @app_commands.describe(id="Subscription ID to pause")
    async def pause(self, interaction: discord.Interaction, id: int) -> None:
        await self._set_active(interaction, id, False)

    @app_commands.command(
        name="resume", description="Resume a paused subscription"
    )
    @app_commands.describe(id="Subscription ID to resume")
    async def resume(self, interaction: discord.Interaction, id: int) -> None:
        await self._set_active(interaction, id, True)

    async def _set_active(
        self, interaction: discord.Interaction, sub_id: int, active: bool
    ) -> None:
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Subscription)
                    .join(User)
                    .where(
                        Subscription.id == sub_id,
                        User.discord_user_id == interaction.user.id,
                    )
                )
                sub = result.scalar_one_or_none()
                if sub is None:
                    await interaction.response.send_message(
                        "Subscription not found or you don't own it.",
                        ephemeral=True,
                    )
                    return

                sub.is_active = active
                await session.commit()

                if not active:
                    try:
                        from gosha.events import emit_subscription_paused
                        await emit_subscription_paused(sub.user_id, sub_id)
                    except Exception:
                        pass

                status = "resumed" if active else "paused"
                await interaction.response.send_message(
                    f"Subscription **#{sub_id}** {status}.", ephemeral=True
                )
        except Exception as exc:
            log.exception("Error in /pause or /resume")
            msg = f"Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)

    # ── /my_searches ────────────────────────────────────────────

    @app_commands.command(
        name="my_searches",
        description="List your current job-search subscriptions",
    )
    async def my_searches(self, interaction: discord.Interaction) -> None:
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Subscription)
                    .join(User)
                    .where(User.discord_user_id == interaction.user.id)
                )
                subs = result.scalars().all()

            if not subs:
                await interaction.response.send_message(
                    "You have no subscriptions. Use `/subscribe` to create one!",
                    ephemeral=True,
                )
                return

            lines = []
            for s in subs:
                status = "active" if s.is_active else "paused"
                kw = ", ".join(s.keywords)
                loc = ", ".join(s.locations)
                line = f"**#{s.id}** [{status}] `{kw}` in `{loc}` (last {s.max_age_days}d)"
                extras = []
                if s.excluded_keywords:
                    extras.append(f"excl: {', '.join(s.excluded_keywords)}")
                if s.company_blacklist:
                    extras.append(f"blacklist: {', '.join(s.company_blacklist)}")
                if s.salary_min:
                    extras.append(f"salary>={s.salary_min}")
                exp = s.experience_levels
                if exp and exp != ["any"]:
                    extras.append(f"exp: {', '.join(exp)}")
                if extras:
                    line += f"\n  {' | '.join(extras)}"
                lines.append(line)

            embed = discord.Embed(
                title="Your Job Subscriptions",
                description="\n".join(lines),
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as exc:
            log.exception("Error in /my_searches")
            msg = f"Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)

    # ── /scrape_now ─────────────────────────────────────────────

    @app_commands.command(
        name="scrape_now", description="Force an immediate scrape cycle"
    )
    async def scrape_now(self, interaction: discord.Interaction) -> None:
        from gosha.pipeline import run_scrape_cycle

        try:
            if self.bot.tunnel_manager is None:
                await interaction.response.send_message(
                    "Bot not fully initialised yet.", ephemeral=True
                )
                return

            await interaction.response.send_message(
                "Scrape started...", ephemeral=True
            )

            # Pass semantic config from bot settings
            kwargs: dict = {
                "bot": self.bot,
                "tunnel_manager": self.bot.tunnel_manager,
                "alert_channel_id": self.bot.alert_channel_id,
            }
            if self.bot.settings:
                kwargs["use_semantic"] = self.bot.settings.use_semantic_matching
                kwargs["semantic_model"] = self.bot.settings.semantic_model
                kwargs["semantic_threshold"] = self.bot.settings.semantic_threshold

            asyncio.create_task(run_scrape_cycle(**kwargs))
        except Exception as exc:
            log.exception("Error in /scrape_now")
            msg = f"Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)

    # ── /stats ──────────────────────────────────────────────────

    @app_commands.command(
        name="stats", description="Show your job delivery statistics"
    )
    async def stats(self, interaction: discord.Interaction) -> None:
        from gosha.models import UserJob
        from sqlalchemy import func

        try:
            async with get_session() as session:
                user_result = await session.execute(
                    select(User).where(User.discord_user_id == interaction.user.id)
                )
                user = user_result.scalar_one_or_none()
                if user is None:
                    await interaction.response.send_message(
                        "No data yet. Subscribe to start receiving jobs!",
                        ephemeral=True,
                    )
                    return

                total = await session.execute(
                    select(func.count(UserJob.id)).where(UserJob.user_id == user.id)
                )
                total_count = total.scalar() or 0

                interested = await session.execute(
                    select(func.count(UserJob.id)).where(
                        UserJob.user_id == user.id,
                        UserJob.feedback == "interested",
                    )
                )
                interested_count = interested.scalar() or 0

                not_relevant = await session.execute(
                    select(func.count(UserJob.id)).where(
                        UserJob.user_id == user.id,
                        UserJob.feedback == "not_relevant",
                    )
                )
                not_relevant_count = not_relevant.scalar() or 0

                sub_count = await session.execute(
                    select(func.count(Subscription.id)).where(
                        Subscription.user_id == user.id,
                        Subscription.is_active == True,
                    )
                )
                active_subs = sub_count.scalar() or 0

            embed = discord.Embed(
                title="Your Job Stats",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Active Subscriptions", value=str(active_subs), inline=True)
            embed.add_field(name="Jobs Delivered", value=str(total_count), inline=True)
            embed.add_field(name="Interested", value=str(interested_count), inline=True)
            embed.add_field(name="Not Relevant", value=str(not_relevant_count), inline=True)

            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as exc:
            log.exception("Error in /stats")
            msg = f"Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
