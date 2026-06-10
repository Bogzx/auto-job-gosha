"""Tests for the Discord OAuth flow (Discord mocked with respx)."""

from __future__ import annotations

import pytest
import respx
from httpx import Response
from sqlalchemy import select

from gosha.models import User

DISCORD_API = "https://discord.com/api/v10"


def _state_for(client) -> tuple[str, dict]:
    """Generate a signed state the same way the login route does."""
    from gosha.api.auth import OAUTH_STATE_COOKIE, make_state

    state = make_state()
    return state, {OAUTH_STATE_COOKIE: state}


def _mock_discord(discord_id: str = "424242", username: str = "gosha",
                  avatar: str | None = "abc123", guild_put_status: int = 201):
    respx.post(f"{DISCORD_API}/oauth2/token").mock(
        return_value=Response(200, json={
            "access_token": "user-access-token",
            "token_type": "Bearer",
        })
    )
    respx.get(f"{DISCORD_API}/users/@me").mock(
        return_value=Response(200, json={
            "id": discord_id,
            "username": username,
            "avatar": avatar,
        })
    )
    respx.put(url__regex=rf"{DISCORD_API}/guilds/\d+/members/\d+").mock(
        return_value=Response(guild_put_status)
    )
    respx.get(url__regex=rf"{DISCORD_API}/guilds/\d+/members/\d+").mock(
        return_value=Response(404)
    )


@pytest.mark.asyncio
async def test_login_redirects_to_discord(client):
    resp = await client.get("/api/v1/auth/discord/login", follow_redirects=False)
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert location.startswith("https://discord.com/oauth2/authorize")
    assert "client_id=1234" in location
    assert "identify+guilds.join" in location or "identify%20guilds.join" in location
    assert "state=" in location
    # State cookie set for CSRF binding
    assert any("gosha_oauth_state" in h for h in resp.headers.get_list("set-cookie"))


@pytest.mark.asyncio
@respx.mock
async def test_callback_creates_user_and_joins_guild(client, session, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "bot-token")
    _mock_discord()
    state, cookies = _state_for(client)

    resp = await client.get(
        "/api/v1/auth/discord/callback",
        params={"code": "the-code", "state": state},
        cookies=cookies,
        follow_redirects=False,
    )

    assert resp.status_code == 307
    assert resp.headers["location"] == "/welcome"
    set_cookies = " ".join(resp.headers.get_list("set-cookie"))
    assert "gosha_session=" in set_cookies

    user = (
        await session.execute(select(User).where(User.discord_user_id == 424242))
    ).scalar_one()
    assert user.username == "gosha"
    assert user.avatar_url == "https://cdn.discordapp.com/avatars/424242/abc123.png"
    assert user.in_guild is True
    assert user.last_login_at is not None


@pytest.mark.asyncio
@respx.mock
async def test_callback_existing_user_redirects_home(client, session, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "bot-token")
    session.add(User(discord_user_id=424242, username="old-name"))
    await session.commit()
    _mock_discord(username="new-name")
    state, cookies = _state_for(client)

    resp = await client.get(
        "/api/v1/auth/discord/callback",
        params={"code": "c", "state": state},
        cookies=cookies,
        follow_redirects=False,
    )

    assert resp.headers["location"] == "/"
    user = (
        await session.execute(select(User).where(User.discord_user_id == 424242))
    ).scalar_one()
    await session.refresh(user)
    assert user.username == "new-name"


@pytest.mark.asyncio
@respx.mock
async def test_callback_guild_join_failure_is_non_fatal(client, session, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "bot-token")
    _mock_discord(guild_put_status=403)
    state, cookies = _state_for(client)

    resp = await client.get(
        "/api/v1/auth/discord/callback",
        params={"code": "c", "state": state},
        cookies=cookies,
        follow_redirects=False,
    )

    assert resp.status_code == 307  # login still succeeds
    user = (
        await session.execute(select(User).where(User.discord_user_id == 424242))
    ).scalar_one()
    assert user.in_guild is False


@pytest.mark.asyncio
async def test_callback_bad_state_rejected(client):
    resp = await client.get(
        "/api/v1/auth/discord/callback",
        params={"code": "c", "state": "forged-state"},
        cookies={"gosha_oauth_state": "forged-state"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_state"


@pytest.mark.asyncio
@respx.mock
async def test_callback_state_cookie_mismatch_rejected(client):
    state, _cookies = _state_for(client)
    other_state, _ = _state_for(client)
    resp = await client.get(
        "/api/v1/auth/discord/callback",
        params={"code": "c", "state": state},
        cookies={"gosha_oauth_state": other_state},
        follow_redirects=False,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_debug_login_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("DEBUG_LOGIN", raising=False)
    resp = await client.get(
        "/api/v1/auth/debug-login", params={"uid": 1}, follow_redirects=False
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_logout_clears_cookie(client, web_user):
    _user, cookies = web_user
    resp = await client.post("/api/v1/auth/logout", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    set_cookie = " ".join(resp.headers.get_list("set-cookie"))
    assert "gosha_session=" in set_cookie  # deletion sets empty value
