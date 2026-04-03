"""Discord slash-command handlers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

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
    _started_at: float = 0.0  # timestamp for uptime tracking
    _last_scrape_at: float = 0.0  # timestamp of last completed scrape

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(command_prefix="!", intents=intents)
        self._started_at = time.monotonic()

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

    # ── keyword autocomplete ────────────────────────────────────

    _KEYWORD_SUGGESTIONS = [
        ("computer science internship — 20 intern/junior roles", "computer science internship"),
        ("computer science — 18 general tech roles", "computer science"),
        ("cs entry level — 11 junior/graduate/trainee roles", "cs entry level"),
        ("tech internship — 9 tech + product + UX intern roles", "tech internship"),
        ("data science — 8 data/ML/AI roles", "data science"),
        ("software engineering — 9 dev roles (frontend, backend, etc.)", "software engineering"),
    ]

    async def _keyword_autocomplete(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        """Suggest smart keywords as the user types."""
        current_lower = current.lower()
        results = []
        for label, value in self._KEYWORD_SUGGESTIONS:
            if current_lower in label.lower() or current_lower in value.lower():
                results.append(app_commands.Choice(name=label[:100], value=value))
        # If the user typed something custom, include it as-is
        if current.strip() and not results:
            results.append(app_commands.Choice(name=current.strip(), value=current.strip()))
        return results[:25]

    # ── location autocomplete ───────────────────────────────────

    async def _location_autocomplete(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        """Suggest known locations as the user types."""
        from gosha.filters import LOCATION_ALIASES

        current_lower = current.lower().strip()
        seen: set[str] = set()
        results: list[app_commands.Choice[str]] = []
        for alias, info in LOCATION_ALIASES.items():
            display = info["search"]
            if display in seen:
                continue
            if current_lower in alias or current_lower in display.lower():
                results.append(app_commands.Choice(name=display, value=alias))
                seen.add(display)
        if current.strip() and not results:
            results.append(app_commands.Choice(name=current.strip(), value=current.strip()))
        return results[:25]

    # ── /subscribe ──────────────────────────────────────────────

    @app_commands.command(
        name="subscribe",
        description="Add a new job-search subscription",
    )
    @app_commands.describe(
        keyword="Search term — pick a smart keyword or type your own",
        location="City or country — start typing for suggestions",
        max_age_days="Only show jobs posted within this many days (default 7)",
        experience="Experience level filter (default: any)",
        exclude="Keywords to exclude, comma-separated. e.g. 'sales, marketing'",
        salary_min="Minimum annual salary (in local currency)",
    )
    @app_commands.choices(experience=[
        app_commands.Choice(name="Any level", value="any"),
        app_commands.Choice(name="Intern / Internship", value="intern"),
        app_commands.Choice(name="Junior / Entry Level", value="junior"),
        app_commands.Choice(name="Mid-level", value="mid"),
        app_commands.Choice(name="Senior+", value="senior"),
    ])
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

                # Build a helpful confirmation showing what will happen
                from gosha.filters import expand_keyword, normalize_location

                kw_display = ", ".join(keywords)
                loc_display = ", ".join(locations)

                # Show expansion info if a smart keyword was used
                expanded = expand_keyword(keywords[0])
                expansion_note = ""
                if len(expanded) > 1:
                    expansion_note = (
                        f"\nThis will search **{len(expanded)} job titles** automatically "
                        f"(e.g. {', '.join(expanded[:3])}, ...)."
                    )

                # Show when jobs will arrive
                interval = self.bot.settings.scrape_interval_minutes if self.bot.settings else 60

                embed = discord.Embed(
                    title=f"Subscribed! #{sub.id}",
                    description=(
                        f"**Keywords:** {kw_display}\n"
                        f"**Location:** {loc_display}\n"
                        f"**Experience:** {experience}\n"
                        f"**Max age:** {max_age_days} days"
                        f"{expansion_note}"
                    ),
                    color=discord.Color.green(),
                )
                embed.set_footer(
                    text=f"Jobs are checked every {interval} min and sent to your DMs. "
                    f"Use /scrape_now to get results immediately."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as exc:
            log.exception("Error in /subscribe")
            msg = f"Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)

    @subscribe.autocomplete("keyword")
    async def _subscribe_keyword_ac(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._keyword_autocomplete(interaction, current)

    @subscribe.autocomplete("location")
    async def _subscribe_location_ac(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._location_autocomplete(interaction, current)

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

    _scrape_cooldown: dict[int, float] = {}  # discord_user_id -> last invocation timestamp
    SCRAPE_COOLDOWN_SECONDS = 300  # 5 minutes between manual scrapes

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

            # Rate limiting
            now = time.monotonic()
            uid = interaction.user.id
            last_used = self._scrape_cooldown.get(uid, 0.0)
            remaining = self.SCRAPE_COOLDOWN_SECONDS - (now - last_used)
            if remaining > 0:
                await interaction.response.send_message(
                    f"Cooldown active — try again in {int(remaining)}s.",
                    ephemeral=True,
                )
                return
            self._scrape_cooldown[uid] = now

            await interaction.response.send_message(
                "Scrape started — I'll DM you when it's done.", ephemeral=True
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

            async def _run_and_notify() -> None:
                try:
                    total = await run_scrape_cycle(**kwargs)
                    self.bot._last_scrape_at = time.monotonic()
                    await interaction.followup.send(
                        f"Scrape complete — **{total}** new jobs delivered.",
                        ephemeral=True,
                    )
                except Exception as exc:
                    log.exception("Scrape cycle failed")
                    await interaction.followup.send(
                        f"Scrape failed: {exc}", ephemeral=True
                    )

            asyncio.create_task(_run_and_notify())
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

    # ── /status ────────────────────────────────────────────────

    @app_commands.command(
        name="status", description="Check bot health and system status"
    )
    async def status(self, interaction: discord.Interaction) -> None:
        try:
            # Uptime
            uptime_secs = int(time.monotonic() - self.bot._started_at)
            hours, remainder = divmod(uptime_secs, 3600)
            minutes, secs = divmod(remainder, 60)
            uptime_str = f"{hours}h {minutes}m {secs}s"

            # Tunnels
            tunnel_mgr = self.bot.tunnel_manager
            if tunnel_mgr:
                proxies = tunnel_mgr.active_proxies()
                total_tunnels = len(tunnel_mgr._tunnels)
                tunnel_str = f"{len(proxies)}/{total_tunnels} active"
            else:
                tunnel_str = "No proxies configured"

            # Last scrape
            if self.bot._last_scrape_at > 0:
                ago = int(time.monotonic() - self.bot._last_scrape_at)
                last_scrape_str = f"{ago // 60}m {ago % 60}s ago"
            else:
                last_scrape_str = "Not yet"

            # Subscription count
            async with get_session() as session:
                sub_count = await session.execute(
                    select(func.count(Subscription.id)).where(
                        Subscription.is_active.is_(True)
                    )
                )
                active_subs = sub_count.scalar() or 0
                user_count = await session.execute(
                    select(func.count(User.id))
                )
                total_users = user_count.scalar() or 0

            # Scrape interval
            interval = self.bot.settings.scrape_interval_minutes if self.bot.settings else 60

            embed = discord.Embed(
                title="GOSHA Status",
                color=discord.Color.green(),
            )
            embed.add_field(name="Uptime", value=uptime_str, inline=True)
            embed.add_field(name="SSH Tunnels", value=tunnel_str, inline=True)
            embed.add_field(name="Last Scrape", value=last_scrape_str, inline=True)
            embed.add_field(name="Active Subscriptions", value=str(active_subs), inline=True)
            embed.add_field(name="Total Users", value=str(total_users), inline=True)
            embed.add_field(name="Scrape Interval", value=f"{interval}m", inline=True)

            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as exc:
            log.exception("Error in /status")
            msg = f"Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)

    # ── /quickstart ────────────────────────────────────────────

    @app_commands.command(
        name="quickstart",
        description="Set up job alerts in one click (CS internships in your chosen city)",
    )
    @app_commands.describe(
        location="Your city — start typing for suggestions (default: Romania)",
    )
    async def quickstart(
        self,
        interaction: discord.Interaction,
        location: str = "romania",
    ) -> None:
        try:
            async with get_session() as session:
                user = await self._get_or_create_user(session, interaction.user.id)

                # Check if user already has subscriptions
                existing = await session.execute(
                    select(func.count(Subscription.id)).where(
                        Subscription.user_id == user.id,
                    )
                )
                if (existing.scalar() or 0) > 0:
                    await interaction.response.send_message(
                        "You already have subscriptions! Use `/my_searches` to view them, "
                        "or `/subscribe` to add more.",
                        ephemeral=True,
                    )
                    return

                sub = Subscription(
                    user_id=user.id,
                    max_age_days=14,
                )
                sub.keywords = ["computer science internship"]
                sub.locations = [location.strip()]
                sub.excluded_keywords = []
                sub.company_blacklist = []
                sub.experience_levels = ["intern", "junior"]
                session.add(sub)
                await session.commit()

                try:
                    from gosha.events import emit_subscription_created
                    await emit_subscription_created(user.id, sub.id, sub.keywords)
                except Exception:
                    pass

            from gosha.filters import normalize_location

            _search_loc, _ = normalize_location(location.strip())
            interval = self.bot.settings.scrape_interval_minutes if self.bot.settings else 60

            embed = discord.Embed(
                title="You're all set!",
                description=(
                    f"Created subscription **#{sub.id}**:\n\n"
                    f"**Searching for:** CS internships & junior roles\n"
                    f"**Location:** {_search_loc}\n"
                    f"**Experience:** Intern + Junior\n"
                    f"**Looking back:** 14 days\n\n"
                    f"This searches **20 job titles** automatically across "
                    f"Indeed, LinkedIn, and Glassdoor."
                ),
                color=discord.Color.green(),
            )
            embed.set_footer(
                text=f"Jobs are checked every {interval} min. "
                f"Use /scrape_now to get results right now!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as exc:
            log.exception("Error in /quickstart")
            msg = f"Error: {exc}"
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)

    @quickstart.autocomplete("location")
    async def _quickstart_location_ac(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._location_autocomplete(interaction, current)

    # ── /help ──────────────────────────────────────────────────

    @app_commands.command(
        name="help", description="Show all commands and how to use them"
    )
    async def help_cmd(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="GOSHA — Job Matching Bot",
            description="I automatically scrape Indeed, LinkedIn & Glassdoor and DM you matching jobs.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="/quickstart [location]",
            value="One-click setup for CS internships. Best way to get started!",
            inline=False,
        )
        embed.add_field(
            name="/subscribe keyword location [options]",
            value=(
                "Create a custom subscription. Smart keywords:\n"
                "`computer science internship` — 20 intern/junior roles\n"
                "`computer science` — 18 general tech roles\n"
                "`cs entry level` — 11 junior/graduate roles\n"
                "`data science` — 8 data/ML/AI roles\n"
                "Or type any custom keyword."
            ),
            inline=False,
        )
        embed.add_field(
            name="/my_searches",
            value="List all your subscriptions with their IDs.",
            inline=True,
        )
        embed.add_field(
            name="/edit id [keyword] [location] ...",
            value="Modify an existing subscription.",
            inline=True,
        )
        embed.add_field(
            name="/unsubscribe id",
            value="Delete a subscription.",
            inline=True,
        )
        embed.add_field(
            name="/pause id  &  /resume id",
            value="Temporarily stop/restart a subscription.",
            inline=True,
        )
        embed.add_field(
            name="/scrape_now",
            value="Force an immediate scrape (5 min cooldown).",
            inline=True,
        )
        embed.add_field(
            name="/stats",
            value="See your delivery statistics.",
            inline=True,
        )
        embed.add_field(
            name="/show_keywords keyword",
            value="See the exact job titles a smart keyword searches for.",
            inline=True,
        )
        embed.set_footer(
            text="Jobs arrive via DM — make sure your DMs are open! "
            "(Server Settings > Privacy > Allow DMs)"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /show_keywords ─────────────────────────────────────────

    @app_commands.command(
        name="show_keywords",
        description="See the exact job titles a smart keyword will search for",
    )
    @app_commands.describe(
        keyword="The keyword to expand — pick from the list or type your own",
    )
    async def show_keywords(
        self, interaction: discord.Interaction, keyword: str,
    ) -> None:
        from gosha.filters import expand_keyword

        terms = expand_keyword(keyword)

        if len(terms) == 1 and terms[0] == keyword:
            await interaction.response.send_message(
                f"`{keyword}` is not a smart keyword — it will be searched as-is on job boards.\n\n"
                f"**Smart keywords** that auto-expand:\n"
                + "\n".join(f"- `{k}`" for k in [
                    "computer science internship",
                    "computer science",
                    "cs entry level",
                    "tech internship",
                    "data science",
                    "software engineering",
                ]),
                ephemeral=True,
            )
            return

        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(terms))
        embed = discord.Embed(
            title=f"Keyword: {keyword}",
            description=f"This will search **{len(terms)} job titles**:\n\n{numbered}",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Each title is searched separately on Indeed, LinkedIn & Glassdoor.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @show_keywords.autocomplete("keyword")
    async def _show_keywords_ac(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._keyword_autocomplete(interaction, current)
