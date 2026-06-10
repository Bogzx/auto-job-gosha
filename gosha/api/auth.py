"""Discord OAuth2 login flow.

Scope `identify` gives us the user's id/username/avatar; `guilds.join`
lets the bot add them to the GOSHA server so DM alerts work without any
manual setup (the join-server funnel).
"""

from __future__ import annotations

import logging
import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from gosha.api.deps import ApiError, clear_session_cookie, set_session_cookie
from gosha.api.schemas import OkOut
from gosha.config import load_web_settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

DISCORD_API = "https://discord.com/api/v10"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
OAUTH_STATE_COOKIE = "gosha_oauth_state"
STATE_MAX_AGE = 600  # seconds to complete the OAuth dance


def _state_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        load_web_settings().session_secret, salt="gosha-oauth-state"
    )


def make_state() -> str:
    return _state_serializer().dumps(secrets.token_urlsafe(16))


def _verify_state(state: str) -> bool:
    try:
        _state_serializer().loads(state, max_age=STATE_MAX_AGE)
        return True
    except BadSignature:
        return False


@router.get("/discord/login")
async def discord_login() -> RedirectResponse:
    settings = load_web_settings()
    state = make_state()
    params = urlencode({
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": "identify guilds.join",
        "state": state,
        "prompt": "none",
    })
    response = RedirectResponse(f"{AUTHORIZE_URL}?{params}", status_code=307)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=STATE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return response


@router.get("/discord/callback")
async def discord_callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    settings = load_web_settings()

    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE, "")
    if not state or state != cookie_state or not _verify_state(state):
        raise ApiError(400, "invalid_state", "OAuth state check failed — try signing in again.")
    if not code:
        raise ApiError(400, "invalid_request", "Discord did not return a code.")

    async with httpx.AsyncClient(timeout=15) as http:
        token_resp = await http.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            log.warning("Discord token exchange failed: %s", token_resp.text[:200])
            raise ApiError(502, "discord_error", "Discord sign-in failed — try again.")
        access_token = token_resp.json().get("access_token", "")

        profile_resp = await http.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if profile_resp.status_code != 200:
            raise ApiError(502, "discord_error", "Could not load your Discord profile.")
        profile = profile_resp.json()

        discord_id = int(profile["id"])
        username = profile.get("username")
        avatar_hash = profile.get("avatar")
        avatar_url = (
            f"https://cdn.discordapp.com/avatars/{profile['id']}/{avatar_hash}.png"
            if avatar_hash
            else None
        )

        in_guild = await _join_guild(http, settings.guild_id, discord_id, access_token)

    from gosha.services.users import upsert_discord_user

    user_id, is_new = await upsert_discord_user(
        discord_id, username, avatar_url, in_guild,
    )

    try:
        from gosha.events import get_event_store
        await get_event_store().emit(
            "web.signin", actor_id=user_id, payload={"new_user": is_new}
        )
    except Exception:
        pass

    response = RedirectResponse("/welcome" if is_new else "/", status_code=307)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    set_session_cookie(response, user_id)
    return response


async def _join_guild(
    http: httpx.AsyncClient, guild_id: int, discord_id: int, access_token: str,
) -> bool:
    """Best-effort: add the user to the GOSHA guild so the bot can DM them."""
    bot_token = os.getenv("DISCORD_TOKEN", "")
    if not guild_id or not bot_token:
        return False
    try:
        resp = await http.put(
            f"{DISCORD_API}/guilds/{guild_id}/members/{discord_id}",
            json={"access_token": access_token},
            headers={"Authorization": f"Bot {bot_token}"},
        )
        if resp.status_code in (201, 204):
            return True
        # PUT can fail for permission reasons while the user is already in
        check = await http.get(
            f"{DISCORD_API}/guilds/{guild_id}/members/{discord_id}",
            headers={"Authorization": f"Bot {bot_token}"},
        )
        return check.status_code == 200
    except httpx.HTTPError as exc:
        log.warning("Guild join failed for %s: %s", discord_id, exc)
        return False


@router.post("/logout", response_model=OkOut)
async def logout(response: Response) -> OkOut:
    clear_session_cookie(response)
    return OkOut()


@router.get("/debug-login")
async def debug_login(uid: int) -> RedirectResponse:
    """Local-testing backdoor: session for an arbitrary user id.

    Hard-disabled unless DEBUG_LOGIN=1 is set — never enable in production.
    """
    if os.getenv("DEBUG_LOGIN") != "1":
        raise ApiError(404, "not_found", "Not found.")
    response = RedirectResponse("/", status_code=307)
    set_session_cookie(response, uid)
    return response
