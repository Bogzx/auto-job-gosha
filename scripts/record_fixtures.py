"""Record trimmed live responses as test fixtures for the scraper adapters."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9",
}
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "scrapers" / "fixtures"


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)

    # eJobs: search payload trimmed to 3 jobs + cities map trimmed to majors
    r = httpx.get("https://api.ejobs.ro/jobs",
                  params={"page": 1, "pageSize": 25, "q": "software"},
                  headers=UA, timeout=30)
    payload = r.json()
    payload["jobs"] = payload["jobs"][:25]
    (FIXTURES / "ejobs_search.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    r = httpx.get("https://api.ejobs.ro/cities", headers=UA, timeout=30)
    cities = r.json()
    (FIXTURES / "ejobs_cities.json").write_text(
        json.dumps(cities, ensure_ascii=False), encoding="utf-8")

    # BestJobs: keyword+location payload trimmed to 5 items
    r = httpx.get("https://api.bestjobs.eu/v1/jobs",
                  params={"keyword": "software", "location": "cluj-napoca-romania"},
                  headers=UA, timeout=30)
    payload = r.json()
    payload["items"] = payload.get("items", [])[:5]
    (FIXTURES / "bestjobs_search.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    # RemoteOK: first 6 job entries (skip the legal notice header object)
    r = httpx.get("https://remoteok.com/api", headers=UA, timeout=30,
                  follow_redirects=True)
    data = r.json()
    jobs = [d for d in data if isinstance(d, dict) and d.get("position")][:6]
    (FIXTURES / "remoteok_feed.json").write_text(
        json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8")

    # Hipo: HTML slice containing the first ~4 job cards
    r = httpx.get("https://www.hipo.ro/locuri-de-munca/cautajob/IT-Software/Cluj-Napoca",
                  headers=UA, timeout=30, follow_redirects=True)
    html = r.text
    matches = list(re.finditer(r'class="job-title"', html))
    end = matches[4].start() if len(matches) > 4 else len(html)
    start = max(0, matches[0].start() - 3000) if matches else 0
    (FIXTURES / "hipo_listing.html").write_text(html[start:end + 2000], encoding="utf-8")

    for f in sorted(FIXTURES.iterdir()):
        print(f.name, f.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
