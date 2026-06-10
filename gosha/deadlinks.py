"""Dead-link detection: postings that 404 get marked inactive.

Job boards remove filled postings; keeping them in the feed wastes the
user's time. A daily job samples active postings older than MIN_AGE_DAYS
(never-checked first, then stalest) and deactivates the ones that are
definitively gone (404/410). Network errors are inconclusive — the job
stays active and gets retried on a later run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from gosha.database import get_session
from gosha.models import Job
from gosha.scrapers.base import DEFAULT_HEADERS

log = logging.getLogger(__name__)

MIN_AGE_DAYS = 7
SAMPLE_SIZE = 200
CHECK_TIMEOUT = 10.0
DEAD_STATUSES = {404, 410}


async def _check_url_status(client: httpx.AsyncClient, url: str) -> int | None:
    """HTTP status for the posting URL; None when the check is inconclusive."""
    try:
        resp = await client.head(url, follow_redirects=True)
        if resp.status_code == 405:  # some boards reject HEAD
            resp = await client.get(url, follow_redirects=True)
        return resp.status_code
    except httpx.HTTPError:
        return None


async def check_dead_links(sample_size: int = SAMPLE_SIZE) -> int:
    """Check a sample of aging active jobs; returns how many were expired."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=MIN_AGE_DAYS)

    async with get_session() as session:
        result = await session.execute(
            select(Job)
            .where(Job.is_active.is_(True), Job.first_seen_at < cutoff)
            .order_by(Job.last_checked_at.asc().nullsfirst())
            .limit(sample_size)
        )
        jobs = list(result.scalars().all())

    if not jobs:
        return 0

    now = datetime.now(timezone.utc)
    expired = 0
    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, timeout=CHECK_TIMEOUT,
    ) as client:
        for job in jobs:
            status = await _check_url_status(client, job.url)

            async with get_session() as session:
                fresh = await session.get(Job, job.id)
                if fresh is None:
                    continue
                fresh.last_checked_at = now
                if status in DEAD_STATUSES:
                    fresh.is_active = False
                    expired += 1
                await session.commit()

            if status in DEAD_STATUSES:
                try:
                    from gosha.events import emit_job_expired
                    await emit_job_expired(job.id)
                except Exception:
                    pass

    if expired:
        log.info("Dead-link check: expired %d of %d sampled jobs", expired, len(jobs))
    return expired
