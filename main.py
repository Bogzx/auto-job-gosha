"""Entry point: boots SSH tunnels, the scheduler, and the Discord bot."""

from __future__ import annotations

import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from bot import JobBot
from config import load_settings
from database import init_db
from ssh_tunnels import SSHTunnelManager
from tasks import run_scrape_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


async def main() -> None:
    settings = load_settings()

    # ── Database ────────────────────────────────────────────────
    await init_db(settings.database_url)
    log.info("Database initialised")

    # ── SSH Tunnels ─────────────────────────────────────────────
    tunnel_mgr = SSHTunnelManager(settings.vps_list)
    if settings.vps_list:
        await tunnel_mgr.start_all()
    else:
        log.warning("No VPS proxies configured – scraper will run without proxies")

    # ── Discord Bot ─────────────────────────────────────────────
    bot = JobBot()
    bot.tunnel_manager = tunnel_mgr
    bot.alert_channel_id = settings.alert_channel_id

    # ── Scheduler ───────────────────────────────────────────────
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_scrape_cycle,
        trigger=IntervalTrigger(minutes=settings.scrape_interval_minutes),
        kwargs={
            "bot": bot,
            "tunnel_manager": tunnel_mgr,
            "alert_channel_id": settings.alert_channel_id,
        },
        id="scrape_cycle",
        name="Periodic job scrape",
        replace_existing=True,
    )

    @bot.event
    async def on_ready() -> None:
        log.info("Bot logged in as %s (id=%s)", bot.user, bot.user.id if bot.user else "?")
        if not scheduler.running:
            scheduler.start()
            log.info(
                "Scheduler started – scraping every %d min",
                settings.scrape_interval_minutes,
            )

    # ── Graceful shutdown ───────────────────────────────────────
    loop = asyncio.get_running_loop()
    _shutting_down = False

    async def shutdown() -> None:
        nonlocal _shutting_down
        if _shutting_down:
            return
        _shutting_down = True
        log.info("Shutting down …")
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await tunnel_mgr.stop_all()
        if not bot.is_closed():
            await bot.close()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(shutdown()))
    except NotImplementedError:
        pass  # signal handlers not supported on Windows

    try:
        await bot.start(settings.discord_token)
    finally:
        await shutdown()


if __name__ == "__main__":
    asyncio.run(main())
