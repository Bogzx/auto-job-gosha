"""eJobs.ro adapter — Romania's largest job board.

Endpoint (probed 2026-06-10): GET https://api.ejobs.ro/jobs?page&pageSize&q=<kw>
The cityId param is ignored server-side, so location filtering happens here
using the public /cities id→name map (fetched once, cached).
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from gosha.filters import normalize_location
from gosha.scrapers.base import DEFAULT_HEADERS, HTTP_TIMEOUT, RawJob, SearchQuery
from gosha.scrapers.salary import parse_salary_range

log = logging.getLogger(__name__)

API_URL = "https://api.ejobs.ro/jobs"
CITIES_URL = "https://api.ejobs.ro/cities"
JOB_URL_TEMPLATE = "https://www.ejobs.ro/user/locuri-de-munca/{slug}/{id}"
PAGE_SIZE = 100

_city_names: dict[int, str] | None = None


async def _get_city_map(client: httpx.AsyncClient) -> dict[int, str]:
    global _city_names
    if _city_names is None:
        resp = await client.get(CITIES_URL)
        resp.raise_for_status()
        _city_names = {
            int(c["id"]): str(c["name"])
            for c in resp.json().get("cities", [])
            if c.get("id") is not None
        }
    return _city_names


def _parse(payload: dict, query: SearchQuery, city_names: dict[int, str]) -> list[RawJob]:
    _search_loc, match_subs = normalize_location(query.location)

    jobs: list[RawJob] = []
    for item in payload.get("jobs", []):
        city_ids = [
            loc.get("cityId") for loc in item.get("locations", [])
            if isinstance(loc, dict)
        ]
        names = [city_names.get(cid, "") for cid in city_ids if cid is not None]
        location_text = ", ".join(n for n in names if n)

        # Client-side location filter (API ignores cityId)
        loc_lower = location_text.lower()
        if match_subs and not any(sub in loc_lower for sub in match_subs):
            continue

        posted_at: datetime | None = None
        raw_date = item.get("creationDate")
        if raw_date:
            try:
                posted_at = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            except ValueError:
                posted_at = None

        salary_min, salary_max, currency = parse_salary_range(
            item.get("salary"), default_currency="RON",
        )

        slug = item.get("slug") or "job"
        job_id = item.get("id")
        if not job_id:
            continue

        company = (item.get("company") or {}).get("name") or "Unknown"
        jobs.append(RawJob(
            url=JOB_URL_TEMPLATE.format(slug=slug, id=job_id),
            title=str(item.get("title", "")),
            company=str(company),
            location=f"{location_text}, Romania" if location_text else "Romania",
            description="",  # list payload has no description; title carries the signal
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=currency,
            posted_at=posted_at,
            source="ejobs",
        ))
    return jobs


class EjobsScraper:
    name = "ejobs"

    async def search(self, query: SearchQuery) -> list[RawJob]:
        try:
            async with httpx.AsyncClient(
                headers=DEFAULT_HEADERS, timeout=HTTP_TIMEOUT, follow_redirects=True,
            ) as client:
                city_names = await _get_city_map(client)
                resp = await client.get(API_URL, params={
                    "page": 1,
                    "pageSize": PAGE_SIZE,
                    "q": query.keyword,
                })
                resp.raise_for_status()
                return _parse(resp.json(), query, city_names)
        except Exception as exc:
            log.warning("eJobs scrape failed for %r: %s", query.keyword, exc)
            return []
