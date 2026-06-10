"""Tests for the scraper plugin core: RawJob records, salary parsing, registry."""

from __future__ import annotations

from datetime import datetime, timezone

from gosha.scrapers.base import RawJob, SearchQuery
from gosha.scrapers.registry import get_extra_scrapers
from gosha.scrapers.salary import parse_salary_range


def test_raw_job_to_record_matches_upsert_columns():
    job = RawJob(
        url="https://x.com/1",
        title="Dev",
        company="Acme",
        location="Cluj-Napoca, Romania",
        description="Build stuff",
        salary_min=5000,
        salary_max=10000,
        salary_currency="RON",
        posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        source="ejobs",
    )
    record = job.to_record()
    assert record["job_url"] == "https://x.com/1"
    assert record["site"] == "ejobs"
    assert record["min_amount"] == 5000
    assert record["max_amount"] == 10000
    assert record["currency"] == "RON"
    assert record["date_posted"] == job.posted_at
    assert record["title"] == "Dev"


def test_parse_salary_range_variants():
    assert parse_salary_range("5000 - 10000 RON") == (5000.0, 10000.0, "RON")
    assert parse_salary_range("900 - 1250", default_currency="EUR") == (900.0, 1250.0, "EUR")
    assert parse_salary_range("3500 RON") == (3500.0, 3500.0, "RON")
    assert parse_salary_range("1.500 - 2.000 EUR") == (1500.0, 2000.0, "EUR")
    assert parse_salary_range("") == (None, None, None)
    assert parse_salary_range(None) == (None, None, None)
    assert parse_salary_range("negotiable") == (None, None, None)


def test_registry_returns_all_extra_sources():
    scrapers = get_extra_scrapers()
    names = {s.name for s in scrapers}
    assert names == {"remoteok", "ejobs", "bestjobs", "hipo"}


def test_search_query_normalized():
    q = SearchQuery(keyword="  Software Engineer ", location="Cluj-Napoca, Romania", max_age_days=14)
    assert q.keyword == "software engineer"
    assert q.location == "Cluj-Napoca, Romania"
