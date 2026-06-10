"""Tests for the subscriptions (saved searches) API."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from gosha.models import Outbox, Subscription

VALID = {
    "name": "Cluj internships",
    "keywords": ["software engineer intern"],
    "locations": ["cluj"],
    "experience_levels": ["intern"],
    "max_age_days": 7,
}


@pytest.mark.asyncio
async def test_create_and_list(client, web_user, session):
    _user, cookies = web_user
    resp = await client.post("/api/v1/subscriptions", json=VALID, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Cluj internships"
    assert body["keywords"] == ["software engineer intern"]
    assert body["notify_discord"] is True
    assert body["is_active"] is True

    resp = await client.get("/api/v1/subscriptions", cookies=cookies)
    items = resp.json()["items"]
    assert len(items) == 1


@pytest.mark.asyncio
async def test_first_subscription_enqueues_welcome_dm(client, web_user, session):
    user, cookies = web_user  # web_user fixture has in_guild=True
    await client.post("/api/v1/subscriptions", json=VALID, cookies=cookies)

    rows = (await session.execute(select(Outbox))).scalars().all()
    assert len(rows) == 1
    assert rows[0].kind == "welcome"
    assert rows[0].user_id == user.id

    # Second subscription does not enqueue another welcome
    second = dict(VALID, name="Another", keywords=["qa intern"])
    await client.post("/api/v1/subscriptions", json=second, cookies=cookies)
    rows = (await session.execute(select(Outbox))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_tier_limits_subscription_count(client, web_user, session):
    user, cookies = web_user
    for i in range(5):  # free tier cap
        sub = Subscription(user_id=user.id)
        sub.keywords = [f"kw{i}"]
        sub.locations = ["cluj"]
        session.add(sub)
    await session.commit()

    resp = await client.post("/api/v1/subscriptions", json=VALID, cookies=cookies)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tier_limit"


@pytest.mark.asyncio
async def test_tier_limits_keyword_count(client, web_user):
    _user, cookies = web_user
    payload = dict(VALID, keywords=[f"kw{i}" for i in range(6)])  # free cap is 5
    resp = await client.post("/api/v1/subscriptions", json=payload, cookies=cookies)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tier_limit"


@pytest.mark.asyncio
async def test_validation_requires_keyword_and_location(client, web_user):
    _user, cookies = web_user
    resp = await client.post(
        "/api/v1/subscriptions",
        json=dict(VALID, keywords=[]),
        cookies=cookies,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_updates_fields(client, web_user):
    _user, cookies = web_user
    created = (
        await client.post("/api/v1/subscriptions", json=VALID, cookies=cookies)
    ).json()

    resp = await client.patch(
        f"/api/v1/subscriptions/{created['id']}",
        json={"notify_discord": False, "salary_min": 2000, "name": "Renamed"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["notify_discord"] is False
    assert body["salary_min"] == 2000
    assert body["name"] == "Renamed"
    assert body["keywords"] == VALID["keywords"]  # untouched


@pytest.mark.asyncio
async def test_pause_resume(client, web_user):
    _user, cookies = web_user
    created = (
        await client.post("/api/v1/subscriptions", json=VALID, cookies=cookies)
    ).json()
    sub_id = created["id"]

    resp = await client.post(f"/api/v1/subscriptions/{sub_id}/pause", cookies=cookies)
    assert resp.json()["is_active"] is False
    resp = await client.post(f"/api/v1/subscriptions/{sub_id}/resume", cookies=cookies)
    assert resp.json()["is_active"] is True


@pytest.mark.asyncio
async def test_delete(client, web_user, session):
    _user, cookies = web_user
    created = (
        await client.post("/api/v1/subscriptions", json=VALID, cookies=cookies)
    ).json()

    resp = await client.delete(
        f"/api/v1/subscriptions/{created['id']}", cookies=cookies
    )
    assert resp.status_code == 200
    subs = (await session.execute(select(Subscription))).scalars().all()
    assert subs == []


@pytest.mark.asyncio
async def test_cross_user_404(client, web_user, session):
    from gosha.models import User
    from tests.api.conftest import session_cookie

    user, _cookies = web_user
    sub = Subscription(user_id=user.id)
    sub.keywords = ["x"]
    sub.locations = ["y"]
    session.add(sub)
    other = User(discord_user_id=31337)
    session.add(other)
    await session.commit()

    resp = await client.delete(
        f"/api/v1/subscriptions/{sub.id}", cookies=session_cookie(other.id)
    )
    assert resp.status_code == 404
