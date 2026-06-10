"""Cross-board job deduplication.

The same posting often appears on Indeed, LinkedIn, and the Romanian
boards. Rows with the same normalized (title, company) within the recent
window form a group: the lowest-id row is canonical (dedup_group_id points
at itself), the rest point at it. Browse/feed only show canonical rows;
each source URL stays in the DB.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from gosha.database import get_session
from gosha.models import Job

log = logging.getLogger(__name__)

WINDOW_DAYS = 30

# Legal suffixes that make "Acme SRL" and "Acme" the same employer
_LEGAL_SUFFIXES = re.compile(
    r"\b(s\.?r\.?l\.?|s\.?a\.?|inc|llc|ltd|gmbh|srl)\b", re.IGNORECASE
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_key(title: str, company: str) -> str:
    company = _LEGAL_SUFFIXES.sub("", company or "")
    title_part = _NON_ALNUM.sub("", (title or "").lower())
    company_part = _NON_ALNUM.sub("", company.lower())
    return f"{title_part}::{company_part}"


async def assign_dedup_groups(window_days: int = WINDOW_DAYS) -> int:
    """Group recent active jobs by normalized key. Returns duplicates marked."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    async with get_session() as session:
        result = await session.execute(
            select(Job).where(
                Job.is_active.is_(True),
                Job.first_seen_at >= cutoff,
            )
        )
        jobs = list(result.scalars().all())

        groups: dict[str, list[Job]] = {}
        for job in jobs:
            groups.setdefault(normalize_key(job.title, job.company), []).append(job)

        duplicates = 0
        changed = False
        for members in groups.values():
            if len(members) < 2:
                continue
            canonical_id = min(job.id for job in members)
            for job in members:
                if job.dedup_group_id != canonical_id:
                    job.dedup_group_id = canonical_id
                    changed = True
                if job.id != canonical_id:
                    duplicates += 1
        if changed:
            await session.commit()

    if duplicates:
        log.info("Dedup: %d duplicate postings grouped", duplicates)
    return duplicates
