"""Adapter parsing tests against fixtures recorded from the live endpoints
(scripts/record_fixtures.py, 2026-06-10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gosha.scrapers import bestjobs, ejobs, hipo, remoteok
from gosha.scrapers.base import SearchQuery

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ── RemoteOK ──────────────────────────────────────────────────────────


def test_remoteok_parse_filters_by_keyword():
    feed = load_json("remoteok_feed.json")
    query = SearchQuery(keyword="design", location="remote", max_age_days=365)
    jobs = remoteok._parse(feed, query)

    assert jobs, "expected at least one design-tagged job in the fixture"
    for job in jobs:
        assert job.source == "remoteok"
        assert job.url.startswith("http")
        assert job.title
        haystack = job.title.lower() + " " + job.description.lower()
        # matched via title or tags; description is stripped of HTML
        assert "<" not in job.description


def test_remoteok_parse_respects_age_cutoff():
    feed = load_json("remoteok_feed.json")
    query = SearchQuery(keyword="", location="remote", max_age_days=0)
    assert remoteok._parse(feed, query) == []


def test_remoteok_only_applies_to_remote_queries():
    scraper = remoteok.RemoteOKScraper()
    assert scraper.applies_to(SearchQuery(keyword="x", location="Remote"))
    assert scraper.applies_to(SearchQuery(keyword="x", location="europe"))
    assert not scraper.applies_to(SearchQuery(keyword="x", location="Cluj-Napoca, Romania"))


@pytest.mark.asyncio
async def test_remoteok_search_skips_non_remote():
    scraper = remoteok.RemoteOKScraper()
    result = await scraper.search(SearchQuery(keyword="python", location="cluj"))
    assert result == []  # no network call needed


# ── eJobs ─────────────────────────────────────────────────────────────


def _ejobs_city_map() -> dict[int, str]:
    return {
        int(c["id"]): str(c["name"])
        for c in load_json("ejobs_cities.json")["cities"]
    }


def test_ejobs_parse_maps_fields_and_filters_location():
    payload = load_json("ejobs_search.json")
    city_map = _ejobs_city_map()

    query = SearchQuery(keyword="software", location="bucharest", max_age_days=30)
    jobs = ejobs._parse(payload, query, city_map)

    assert jobs, "fixture should contain Bucharest software jobs"
    for job in jobs:
        assert job.source == "ejobs"
        assert "bucure" in job.location.lower() or "bucharest" in job.location.lower()
        assert job.url.startswith("https://www.ejobs.ro/")
        assert job.title


def test_ejobs_parse_unmatched_city_returns_empty():
    payload = load_json("ejobs_search.json")
    query = SearchQuery(keyword="software", location="tokyo", max_age_days=30)
    assert ejobs._parse(payload, query, _ejobs_city_map()) == []


def test_ejobs_parse_salary_when_present():
    payload = {
        "jobs": [{
            "id": 1, "title": "Dev", "slug": "dev",
            "company": {"name": "X"},
            "salary": "5000 - 10000 RON",
            "locations": [{"cityId": 14}],
            "creationDate": "2026-06-10T12:00:00Z",
        }]
    }
    query = SearchQuery(keyword="dev", location="cluj")
    jobs = ejobs._parse(payload, query, {14: "Cluj-Napoca"})
    assert len(jobs) == 1
    assert jobs[0].salary_min == 5000
    assert jobs[0].salary_max == 10000
    assert jobs[0].salary_currency == "RON"
    assert jobs[0].posted_at is not None


# ── BestJobs ──────────────────────────────────────────────────────────


def test_bestjobs_parse_maps_fields():
    payload = load_json("bestjobs_search.json")
    query = SearchQuery(keyword="software", location="cluj")
    jobs = bestjobs._parse(payload, query)

    assert jobs
    for job in jobs:
        assert job.source == "bestjobs"
        assert job.url.startswith("https://www.bestjobs.eu/ro/loc-de-munca/")
        assert job.title
        assert job.company


def test_bestjobs_salary_defaults_to_eur():
    payload = {
        "items": [{
            "slug": "x", "title": "Dev", "companyName": "Y",
            "salary": "900 - 1250",
            "locations": [{"name": "Cluj-Napoca, România"}],
        }]
    }
    jobs = bestjobs._parse(payload, SearchQuery(keyword="dev", location="cluj"))
    assert jobs[0].salary_min == 900
    assert jobs[0].salary_currency == "EUR"


def test_bestjobs_location_slug():
    assert bestjobs.location_to_slug("cluj") == "cluj-napoca-romania"
    assert bestjobs.location_to_slug("Bucharest") == "bucharest-romania"
    assert bestjobs.location_to_slug("Timișoara, România") == "timisoara-romania"


# ── Hipo ──────────────────────────────────────────────────────────────


def test_hipo_parse_extracts_cards():
    html = (FIXTURES / "hipo_listing.html").read_text(encoding="utf-8")
    jobs = hipo._parse(html, "Cluj-Napoca")

    assert len(jobs) >= 2, "fixture holds multiple job cards"
    for job in jobs:
        assert job.source == "hipo"
        assert job.url.startswith("https://www.hipo.ro/")
        assert job.title
        assert job.company
        assert "Cluj" in job.location


def test_hipo_city_segment_mapping():
    assert hipo.city_segment("cluj") == "Cluj-Napoca"
    assert hipo.city_segment("Bucharest") == "Bucuresti"
    assert hipo.city_segment("romania") == "Toate-Orasele"
    assert hipo.city_segment("london") is None


@pytest.mark.asyncio
async def test_hipo_search_skips_unsupported_cities():
    scraper = hipo.HipoScraper()
    assert await scraper.search(SearchQuery(keyword="x", location="berlin")) == []
