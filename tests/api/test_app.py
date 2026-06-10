"""Tests for the API skeleton: health, error envelope, session auth."""

from __future__ import annotations

import pytest

from tests.api.conftest import session_cookie


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_me_unauthenticated(client):
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "unauthenticated"
    assert "message" in body["error"]


@pytest.mark.asyncio
async def test_me_with_valid_cookie(client, web_user):
    user, cookies = web_user
    resp = await client.get("/api/v1/me", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == user.id
    assert body["discord_id"] == str(user.discord_user_id)
    assert body["username"] == "gosha"
    assert body["in_guild"] is True
    assert body["is_admin"] is False
    assert body["tier"] == "free"
    assert body["has_cv"] is False


@pytest.mark.asyncio
async def test_me_admin_flag(client, admin_user_fixture):
    _user, cookies = admin_user_fixture
    resp = await client.get("/api/v1/me", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is True


@pytest.mark.asyncio
async def test_tampered_cookie_rejected(client, web_user):
    _user, cookies = web_user
    cookie_name = next(iter(cookies))
    resp = await client.get(
        "/api/v1/me", cookies={cookie_name: cookies[cookie_name] + "x"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cookie_for_deleted_user_rejected(client):
    resp = await client.get("/api/v1/me", cookies=session_cookie(424242))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unknown_route_envelope(client):
    resp = await client.get("/api/v1/definitely-not-a-route")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
