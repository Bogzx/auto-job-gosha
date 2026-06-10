"""Tests for eJobs description enrichment from the detail endpoint."""

from __future__ import annotations

import json
from pathlib import Path

from gosha.scrapers import ejobs
from gosha.scrapers.base import SearchQuery

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_description_from_detail():
    detail = json.loads((FIXTURES / "ejobs_detail.json").read_text(encoding="utf-8"))
    text = ejobs._extract_description(detail)

    assert text, "real detail fixture should yield a description"
    assert "<" not in text  # HTML stripped
    assert len(text) > 100


def test_extract_description_handles_missing_details():
    assert ejobs._extract_description({}) == ""
    assert ejobs._extract_description({"details": {}}) == ""
    assert ejobs._extract_description({"details": {"jobDescription": None}}) == ""


def test_parse_attaches_provided_descriptions():
    payload = {
        "jobs": [{
            "id": 7, "title": "Dev", "slug": "dev",
            "company": {"name": "X"},
            "locations": [{"cityId": 14}],
        }]
    }
    query = SearchQuery(keyword="dev", location="cluj")
    jobs = ejobs._parse(
        payload, query, {14: "Cluj-Napoca"},
        descriptions={7: "Responsibilities: write Python."},
    )
    assert jobs[0].description == "Responsibilities: write Python."
