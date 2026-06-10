"""Hipo.ro adapter — student/graduate-focused Romanian board.

No public API; we parse the IT-Software listing HTML per city:
https://www.hipo.ro/locuri-de-munca/cautajob/IT-Software/<City>
(card structure probed 2026-06-10: a.job-title[title][href] + p.company-name).
Keyword relevance is left to GOSHA's own filters/semantic matching since
Hipo's IT-Software domain already narrows the field.
"""

from __future__ import annotations

import logging
import re

import httpx

from gosha.filters import normalize_location
from gosha.scrapers.base import DEFAULT_HEADERS, HTTP_TIMEOUT, RawJob, SearchQuery

log = logging.getLogger(__name__)

BASE_URL = "https://www.hipo.ro"
LISTING_URL = BASE_URL + "/locuri-de-munca/cautajob/IT-Software/{city}"

# City segment names hipo uses in its catalog URLs
CITY_SEGMENTS = {
    "bucharest": "Bucuresti",
    "bucuresti": "Bucuresti",
    "cluj-napoca": "Cluj-Napoca",
    "timisoara": "Timisoara",
    "iasi": "Iasi",
    "brasov": "Brasov",
    "sibiu": "Sibiu",
    "craiova": "Craiova",
    "constanta": "Constanta",
    "oradea": "Oradea",
    "romania": "Toate-Orasele",
}

_CARD_RE = re.compile(
    r'<a\s+title="(?P<title>[^"]+)"\s+class="job-title"\s+href="(?P<href>[^"]+)".*?'
    r'<p class="company-name">\s*(?:<span>)?(?P<company>[^<]*)',
    re.DOTALL,
)


def city_segment(location: str) -> str | None:
    """Map a user location to hipo's URL segment; None when unsupported."""
    search_loc, _subs = normalize_location(location)
    city = search_loc.split(",")[0].strip().lower()
    city = (
        city.replace("ă", "a").replace("â", "a").replace("î", "i")
        .replace("ș", "s").replace("ş", "s").replace("ț", "t").replace("ţ", "t")
    )
    return CITY_SEGMENTS.get(city)


def _parse(html: str, city_label: str) -> list[RawJob]:
    jobs: list[RawJob] = []
    for match in _CARD_RE.finditer(html):
        href = match.group("href").strip()
        title = match.group("title").strip()
        company = match.group("company").strip() or "Unknown"
        if not href or not title:
            continue
        url = href if href.startswith("http") else BASE_URL + href
        jobs.append(RawJob(
            url=url,
            title=title,
            company=company,
            location=f"{city_label}, Romania" if city_label != "Toate-Orasele" else "Romania",
            description="",
            source="hipo",
        ))
    return jobs


class HipoScraper:
    name = "hipo"

    async def search(self, query: SearchQuery) -> list[RawJob]:
        segment = city_segment(query.location)
        if segment is None:
            return []  # hipo is Romania-only
        try:
            async with httpx.AsyncClient(
                headers=DEFAULT_HEADERS, timeout=HTTP_TIMEOUT, follow_redirects=True,
            ) as client:
                resp = await client.get(LISTING_URL.format(city=segment))
                resp.raise_for_status()
                return _parse(resp.text, segment.replace("-", " "))
        except Exception as exc:
            log.warning("Hipo scrape failed for %r: %s", query.location, exc)
            return []
