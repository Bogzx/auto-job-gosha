"""Discord slash-command handlers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from database import Subscription, User, get_session

if TYPE_CHECKING:
    from ssh_tunnels import SSHTunnelManager

log = logging.getLogger(__name__)


class JobBot(commands.Bot):
    """Custom Bot subclass so we can sync the command tree on ready."""

    tunnel_manager: SSHTunnelManager | None = None
    alert_channel_id: int = 0

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        await self.add_cog(SubscriptionCog(self))
        await self.tree.sync()
        log.info("Slash commands synced")

        @self.tree.error
        async def on_app_command_error(
            interaction: discord.Interaction, error: app_commands.AppCommandError
        ) -> None:
            log.exception("Slash command error: %s", error)
            msg = f"❌ Something went wrong: {error}"
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

    # ── /subscribe ──────────────────────────────────────────────

    @app_commands.command(name="subscribe", description="Add a new job-search subscription")
    @app_commands.describe(
        keyword="Search term, e.g. 'Computer Science Internship'",
        location="Location filter, e.g. 'Dublin'",
        max_age_days="Only show jobs posted within this many days (default 7)",
    )
    async def subscribe(
        self,
        interaction: discord.Interaction,
        keyword: str,
        location: str,
        max_age_days: int = 7,
    ) -> None:
        try:
            async with get_session() as session:
                # Ensure user row exists
                result = await session.execute(
                    select(User).where(User.discord_user_id == interaction.user.id)
                )
                user = result.scalar_one_or_none()
                if user is None:
                    user = User(discord_user_id=interaction.user.id)
                    session.add(user)
                    await session.flush()

                sub = Subscription(
                    user_id=user.id,
                    keyword=keyword.strip(),
                    location=location.strip(),
                    max_age_days=max_age_days,
                )
                session.add(sub)
                await session.commit()

                await interaction.response.send_message(
                    f"✅ Subscribed! **#{sub.id}** — `{keyword}` in `{location}` (last {max_age_days}d)",
                    ephemeral=True,
                )
        except Exception as exc:
            log.exception("Error in /subscribe")
            msg = f"❌ Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)

    # ── /unsubscribe ────────────────────────────────────────────

    @app_commands.command(name="unsubscribe", description="Remove one of your subscriptions by ID")
    @app_commands.describe(id="Subscription ID shown by /my_searches")
    async def unsubscribe(self, interaction: discord.Interaction, id: int) -> None:
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Subscription)
                    .join(User)
                    .where(Subscription.id == id, User.discord_user_id == interaction.user.id)
                )
                sub = result.scalar_one_or_none()
                if sub is None:
                    await interaction.response.send_message(
                        "\u274c Subscription not found or you don't own it.", ephemeral=True
                    )
                    return

                await session.delete(sub)
                await session.commit()

                await interaction.response.send_message(
                    f"\ud83d\uddd1\ufe0f Subscription **#{id}** removed.", ephemeral=True
                )
        except Exception as exc:
            log.exception("Error in /unsubscribe")
            msg = f"\u274c Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)

    # ── /my_searches ────────────────────────────────────────────

    @app_commands.command(name="my_searches", description="List your current job-search subscriptions")
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
                    "You have no active subscriptions. Use `/subscribe` to create one!",
                    ephemeral=True,
                )
                return

            lines = [
                f"**#{s.id}** — `{s.keyword}` in `{s.location}` (last {s.max_age_days}d)"
                for s in subs
            ]
            embed = discord.Embed(
                title="Your Job Subscriptions",
                description="\n".join(lines),
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as exc:
            log.exception("Error in /my_searches")
            msg = f"❌ Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)

    # ── /scrape_now ─────────────────────────────────────────────

    @app_commands.command(name="scrape_now", description="Force an immediate scrape cycle")
    async def scrape_now(self, interaction: discord.Interaction) -> None:
        from tasks import run_scrape_cycle

        try:
            if self.bot.tunnel_manager is None:
                await interaction.response.send_message(
                    "❌ Bot not fully initialised yet.", ephemeral=True
                )
                return

            await interaction.response.send_message("🔄 Scrape started…", ephemeral=True)
            asyncio.create_task(
                run_scrape_cycle(
                    bot=self.bot,
                    tunnel_manager=self.bot.tunnel_manager,
                    alert_channel_id=self.bot.alert_channel_id,
                )
            )
        except Exception as exc:
            log.exception("Error in /scrape_now")
            msg = f"❌ Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
