"""Fixtures for API tests: app + client wired to the in-memory test DB."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from gosha.models import User


@pytest.fixture
def web_env(monkeypatch):
    """Minimal env vars the web settings require."""
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "1234")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "shhh")
    monkeypatch.setenv("DISCORD_GUILD_ID", "555000")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("ADMIN_DISCORD_IDS", "999999")


@pytest_asyncio.fixture
async def client(web_env, patched_db):
    from gosha.api.app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def session_cookie(user_id: int) -> dict[str, str]:
    """Build a valid signed session cookie for the given user id."""
    from gosha.api.deps import COOKIE_NAME, serializer

    return {COOKIE_NAME: serializer().dumps({"uid": user_id})}


@pytest_asyncio.fixture
async def web_user(session):
    """A normal signed-in user; returns (user, cookies)."""
    user = User(discord_user_id=111222333, username="gosha", in_guild=True)
    session.add(user)
    await session.commit()
    return user, session_cookie(user.id)


@pytest_asyncio.fixture
async def admin_user_fixture(session):
    """An admin user (discord id present in ADMIN_DISCORD_IDS)."""
    user = User(discord_user_id=999999, username="bogdan")
    session.add(user)
    await session.commit()
    return user, session_cookie(user.id)
