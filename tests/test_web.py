"""Tests for the admin-only web dashboard."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from gosha.models import Job, Subscription, User, UserJob


@pytest_asyncio.fixture
async def patched_db(engine, monkeypatch):
    import gosha.database as db_mod

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "_engine", engine)
    monkeypatch.setattr(db_mod, "_session_factory", factory)
    yield factory


@pytest.fixture
def client(patched_db):
    """Create a FastAPI TestClient with patched DB."""
    from fastapi.testclient import TestClient
    from gosha.web.app import app

    return TestClient(app)


@pytest_asyncio.fixture
async def test_data(session, patched_db):
    """Create test user, subscription, and jobs."""
    user = User(discord_user_id=99999)
    session.add(user)
    await session.flush()

    sub = Subscription(user_id=user.id)
    sub.keywords = ["software engineer"]
    sub.locations = ["Cluj"]
    sub.excluded_keywords = []
    sub.company_blacklist = []
    sub.experience_levels = ["any"]
    session.add(sub)
    await session.flush()

    for i in range(3):
        job = Job(
            url=f"https://test.com/job/{i}",
            title=f"Dev Role {i}",
            company=f"Company{i}",
            location="Cluj",
            source="indeed",
        )
        session.add(job)
    await session.flush()
    await session.commit()
    return user


class TestRootRedirect:
    def test_root_redirects_to_admin(self, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "/admin/" in resp.headers.get("location", "")


class TestAdminDashboard:
    def test_admin_page_loads(self, client):
        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert "GOSHA" in resp.text


class TestAdminStats:
    @pytest.mark.asyncio
    async def test_stats(self, client, test_data):
        resp = client.get("/admin/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_users"] >= 1
        assert data["total_subscriptions"] >= 1


class TestAdminUsers:
    @pytest.mark.asyncio
    async def test_list_users(self, client, test_data):
        resp = client.get("/admin/api/users")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert len(data["users"]) >= 1


class TestAdminJobs:
    @pytest.mark.asyncio
    async def test_list_jobs(self, client, test_data):
        resp = client.get("/admin/api/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 3
