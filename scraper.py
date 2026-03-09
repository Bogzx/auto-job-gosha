"""Wrapper around JobSpy that routes requests through a random SOCKS5 tunnel."""

from __future__ import annotations

import asyncio
import logging
import random
from functools import partial
from typing import TYPE_CHECKING

import pandas as pd
from jobspy import scrape_jobs

if TYPE_CHECKING:
    from ssh_tunnels import SSHTunnelManager

log = logging.getLogger(__name__)


async def search_jobs(
    tunnel_manager: SSHTunnelManager,
    keyword: str,
    location: str,
    max_age_days: int,
) -> pd.DataFrame:
    """Run a JobSpy scrape through a randomly chosen active proxy.

    Returns a DataFrame of job results (may be empty).
    """
    proxies = tunnel_manager.active_proxies()
    if not proxies:
        log.warning("No active proxies available – skipping search for '%s' in '%s'", keyword, location)
        return pd.DataFrame()

    # Shuffle so we spread load across VPS instances
    random.shuffle(proxies)

    last_error: Exception | None = None
    for proxy in proxies:
        try:
            log.info("Searching '%s' in '%s' (max_age=%dd) via %s", keyword, location, max_age_days, proxy)
            loop = asyncio.get_running_loop()
            df: pd.DataFrame = await loop.run_in_executor(
                None,
                partial(
                    scrape_jobs,
                    site_name=["indeed", "linkedin", "glassdoor"],
                    search_term=keyword,
                    location=location,
                    results_wanted=50,
                    hours_old=max_age_days * 24,
                    proxy=proxy,
                ),
            )
            log.info("Found %d results for '%s' in '%s'", len(df), keyword, location)
            return df
        except Exception as exc:
            log.error("Proxy %s failed for '%s': %s", proxy, keyword, exc)
            last_error = exc

    log.error("All proxies failed for '%s' in '%s'. Last error: %s", keyword, location, last_error)
    return pd.DataFrame()
