"""Tests for extra-source integration in the scrape stage + posted_at."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest
from sqlalchemy import select

import gosha.pipeline as pipeline
from gosha.models import Job, Subscription, User
from gosha.scrapers.base import RawJob


@pytest.mark.asyncio
async def test_upsert_jobs_sets_posted_at(patched_db, session):
    posted = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([{
        "job_url": "https://p.com/1",
        "title": "Python Dev",
        "company": "Acme",
        "location": "Cluj-Napoca, Romania",
        "description": "desc",
        "site": "ejobs",
        "min_amount": 5000.0,
        "max_amount": 9000.0,
        "currency": "RON",
        "date_posted": posted,
    }])

    jobs = await pipeline.upsert_jobs(df)
    assert len(jobs) == 1

    stored = (
        await session.execute(select(Job).where(Job.url == "https://p.com/1"))
    ).scalar_one()
    assert stored.posted_at is not None
    assert stored.posted_at.replace(tzinfo=timezone.utc) == posted
    assert stored.source == "ejobs"


@pytest.mark.asyncio
async def test_scrape_stage_includes_extra_sources(patched_db, session, monkeypatch):
    user = User(discord_user_id=5005)
    session.add(user)
    await session.flush()
    sub = Subscription(user_id=user.id, max_age_days=7)
    sub.keywords = ["python developer"]
    sub.locations = ["cluj"]
    session.add(sub)
    await session.commit()

    # JobSpy path returns nothing this cycle
    async def fake_jobspy(tunnel_manager, keyword, location, max_age_days, boards=None):
        return pd.DataFrame()

    monkeypatch.setattr("gosha.scraper.scrape_jobs_raw", fake_jobspy)

    class FakeScraper:
        name = "ejobs"

        def __init__(self):
            self.calls: list = []

        async def search(self, query):
            self.calls.append(query)
            return [RawJob(
                url="https://fake.ejobs.ro/python-dev/1",
                title="Python Developer",
                company="FakeCorp",
                location="Cluj-Napoca, Romania",
                source="ejobs",
                posted_at=datetime.now(timezone.utc),
            )]

    fake = FakeScraper()
    monkeypatch.setattr(
        "gosha.scrapers.registry.get_extra_scrapers", lambda: [fake]
    )

    class DummyTunnels:
        def active_proxies(self):
            return []

    jobs = await pipeline.run_scrape_stage(DummyTunnels())

    assert fake.calls, "extra scraper should be invoked"
    urls = {j.url for j in jobs}
    assert "https://fake.ejobs.ro/python-dev/1" in urls

    stored = (
        await session.execute(select(Job).where(Job.source == "ejobs"))
    ).scalars().all()
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_scrape_stage_survives_broken_extra_scraper(patched_db, session, monkeypatch):
    user = User(discord_user_id=5006)
    session.add(user)
    await session.flush()
    sub = Subscription(user_id=user.id, max_age_days=7)
    sub.keywords = ["qa"]
    sub.locations = ["cluj"]
    session.add(sub)
    await session.commit()

    async def fake_jobspy(tunnel_manager, keyword, location, max_age_days, boards=None):
        return pd.DataFrame([{
            "job_url": "https://indeed.com/ok",
            "title": "QA Engineer",
            "company": "Fine Inc",
            "location": "Cluj-Napoca, Romania",
            "site": "indeed",
        }])

    monkeypatch.setattr("gosha.scraper.scrape_jobs_raw", fake_jobspy)

    class ExplodingScraper:
        name = "bestjobs"

        async def search(self, query):
            raise RuntimeError("kaboom")  # adapters shouldn't raise, but if one does...

    monkeypatch.setattr(
        "gosha.scrapers.registry.get_extra_scrapers", lambda: [ExplodingScraper()]
    )

    class DummyTunnels:
        def active_proxies(self):
            return []

    jobs = await pipeline.run_scrape_stage(DummyTunnels())
    assert {j.url for j in jobs} == {"https://indeed.com/ok"}  # cycle survived
