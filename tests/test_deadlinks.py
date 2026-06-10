"""Tests for dead-link detection (404/410 postings get deactivated)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from gosha import deadlinks
from gosha.models import Job


def make_job(url: str, days_old: int = 10, **kwargs) -> Job:
    job = Job(
        url=url,
        title=kwargs.pop("title", "Dev"),
        company="Acme",
        source=kwargs.pop("source", "indeed"),
        **kwargs,
    )
    job.first_seen_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    return job


@pytest.mark.asyncio
async def test_dead_jobs_deactivated(patched_db, session, monkeypatch):
    dead = make_job("https://x.com/dead")
    alive = make_job("https://x.com/alive")
    session.add_all([dead, alive])
    await session.commit()

    async def fake_status(client, url: str) -> int | None:
        return 404 if "dead" in url else 200

    monkeypatch.setattr(deadlinks, "_check_url_status", fake_status)

    expired = await deadlinks.check_dead_links()
    assert expired == 1

    await session.refresh(dead)
    await session.refresh(alive)
    assert dead.is_active is False
    assert alive.is_active is True
    assert dead.last_checked_at is not None
    assert alive.last_checked_at is not None


@pytest.mark.asyncio
async def test_fresh_jobs_not_checked(patched_db, session, monkeypatch):
    fresh = make_job("https://x.com/fresh", days_old=2)
    session.add(fresh)
    await session.commit()

    calls: list[str] = []

    async def fake_status(client, url: str) -> int | None:
        calls.append(url)
        return 404

    monkeypatch.setattr(deadlinks, "_check_url_status", fake_status)
    await deadlinks.check_dead_links()

    assert calls == []
    await session.refresh(fresh)
    assert fresh.is_active is True


@pytest.mark.asyncio
async def test_network_errors_leave_job_active(patched_db, session, monkeypatch):
    job = make_job("https://x.com/flaky")
    session.add(job)
    await session.commit()

    async def fake_status(client, url: str) -> int | None:
        return None  # timeout / connection error

    monkeypatch.setattr(deadlinks, "_check_url_status", fake_status)
    expired = await deadlinks.check_dead_links()

    assert expired == 0
    await session.refresh(job)
    assert job.is_active is True
    assert job.last_checked_at is not None  # still stamped — retried later


@pytest.mark.asyncio
async def test_oldest_checked_first_and_sample_capped(patched_db, session, monkeypatch):
    now = datetime.now(timezone.utc)
    never_checked = make_job("https://x.com/never")
    recently_checked = make_job("https://x.com/recent")
    recently_checked.last_checked_at = now - timedelta(hours=1)
    session.add_all([never_checked, recently_checked])
    await session.commit()

    checked: list[str] = []

    async def fake_status(client, url: str) -> int | None:
        checked.append(url)
        return 200

    monkeypatch.setattr(deadlinks, "_check_url_status", fake_status)
    await deadlinks.check_dead_links(sample_size=1)

    assert checked == ["https://x.com/never"]  # never-checked goes first
