"""Live smoke test: run every adapter against the real endpoints."""

from __future__ import annotations

import asyncio

from gosha.scrapers.base import SearchQuery
from gosha.scrapers.registry import get_extra_scrapers


async def main() -> None:
    queries = [
        SearchQuery(keyword="software engineer", location="cluj", max_age_days=14),
        SearchQuery(keyword="python developer", location="remote", max_age_days=14),
    ]
    for scraper in get_extra_scrapers():
        for query in queries:
            jobs = await scraper.search(query)
            print(f"{scraper.name:10s} {query.keyword!r} @ {query.location!r}: {len(jobs)} jobs")
            for job in jobs[:2]:
                salary = f" | {job.salary_min}-{job.salary_max} {job.salary_currency}" if job.salary_min else ""
                print(f"    {job.title[:50]:50s} | {job.company[:24]:24s} | {job.location[:30]}{salary}")


if __name__ == "__main__":
    asyncio.run(main())
