"""Tests for the web dashboard — auth, API routes, session management."""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from gosha.models import Job, Subscription, User, UserJob
from gosha.web.auth import SessionManager


# ── SessionManager ────────────────────────────────────────────────────


class TestSessionManager:
    def test_create_and_validate(self):
        mgr = SessionManager(secret_key="test-secret")
        token = mgr.create_session(discord_id=12345, username="testuser")
        data = mgr.get_session(token)
        assert data is not None
        assert data["discord_id"] == 12345
        assert data["username"] == "testuser"

    def test_invalid_token(self):
        mgr = SessionManager(secret_key="test-secret")
        assert mgr.get_session("invalid.token") is None
        assert mgr.get_session("") is None
        assert mgr.get_session("no-dot-here") is None

    def test_tampered_token(self):
        mgr = SessionManager(secret_key="test-secret")
        token = mgr.create_session(discord_id=12345, username="testuser")
        # Tamper with the signature
        parts = token.rsplit(".", 1)
        tampered = parts[0] + ".0000000000000000"
        assert mgr.get_session(tampered) is None

    def test_different_secret_rejects(self):
        mgr1 = SessionManager(secret_key="secret-1")
        mgr2 = SessionManager(secret_key="secret-2")
        token = mgr1.create_session(discord_id=12345, username="user")
        assert mgr2.get_session(token) is None

    def test_expired_token(self):
        mgr = SessionManager(secret_key="test-secret", max_age=1)
        token = mgr.create_session(discord_id=12345, username="user")
        # Token should be valid immediately
        assert mgr.get_session(token) is not None
        # After expiry it should be invalid
        import time as _time
        _time.sleep(1.5)
        assert mgr.get_session(token) is None


# ── FastAPI routes (using TestClient) ─────────────────────────────────


@pytest_asyncio.fixture
async def patched_db(engine, monkeypatch):
    import gosha.database as db_mod

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "_engine", engine)
    monkeypatch.setattr(db_mod, "_session_factory", factory)
    yield factory


@pytest.fixture
def client(patched_db, monkeypatch):
    """Create a FastAPI TestClient with patched DB."""
    from fastapi.testclient import TestClient
    from gosha.web.app import app, session_mgr

    # Override session manager secret for tests
    monkeypatch.setattr(session_mgr, "_secret", b"test-secret")

    return TestClient(app)


@pytest.fixture
def auth_cookie():
    """Create a valid session cookie."""
    mgr = SessionManager(secret_key="test-secret")
    token = mgr.create_session(discord_id=99999, username="testbot")
    return {"session": token}


@pytest_asyncio.fixture
async def test_user_with_data(session, patched_db):
    """Create a test user with subscriptions and job deliveries."""
    from sqlalchemy.ext.asyncio import AsyncSession

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

    jobs = []
    for i in range(5):
        job = Job(
            url=f"https://test.com/web/{i}",
            title=f"Dev Role {i}",
            company=f"Company{i}",
            location="Cluj",
            source="indeed",
        )
        session.add(job)
        jobs.append(job)
    await session.flush()

    for job in jobs:
        uj = UserJob(user_id=user.id, job_id=job.id, relevance_score=0.8)
        session.add(uj)

    # Add feedback on some
    await session.commit()
    return user


class TestIndexPage:
    def test_index_no_auth(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "GOSHA" in resp.text

    def test_index_with_auth(self, client, auth_cookie):
        resp = client.get("/", cookies=auth_cookie)
        assert resp.status_code == 200
        assert "testbot" in resp.text


class TestDashboard:
    def test_dashboard_redirects_without_auth(self, client):
        resp = client.get("/dashboard", follow_redirects=False)
        assert resp.status_code in (302, 303, 307)
        assert "/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_dashboard_with_auth(self, client, auth_cookie, test_user_with_data):
        resp = client.get("/dashboard", cookies=auth_cookie)
        assert resp.status_code == 200
        assert "testbot" in resp.text


class TestAPIJobs:
    def test_api_jobs_no_auth(self, client):
        resp = client.get("/api/jobs")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_api_jobs_with_auth(self, client, auth_cookie, test_user_with_data):
        resp = client.get("/api/jobs", cookies=auth_cookie)
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert data["total"] == 5
        assert len(data["jobs"]) == 5


class TestAPISubscriptions:
    def test_no_auth(self, client):
        resp = client.get("/api/subscriptions")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_with_auth(self, client, auth_cookie, test_user_with_data):
        resp = client.get("/api/subscriptions", cookies=auth_cookie)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["keywords"] == ["software engineer"]


class TestAPIStats:
    def test_no_auth(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_with_auth(self, client, auth_cookie, test_user_with_data):
        resp = client.get("/api/stats", cookies=auth_cookie)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_delivered"] == 5


class TestAPIFeedback:
    def test_no_auth(self, client):
        resp = client.post("/api/feedback/1?feedback=interested")
        assert resp.status_code == 401
