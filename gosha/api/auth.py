"""Discord OAuth2 login flow.

Scope `identify` gives us the user's id/username/avatar; `guilds.join`
lets the bot add them to the GOSHA server so DM alerts work without any
manual setup (the join-server funnel).
"""

from __future__ import annotations

import logging
import os
import secrets
import time
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


# States are single-use: once a callback consumes one, replays fail.
# In-memory is fine — one API process, and states expire in 10 minutes.
_consumed_states: dict[str, float] = {}


def _consume_state(state: str) -> bool:
    """Mark a state used; False when it was already consumed."""
    now = time.monotonic()
    for key, expiry in list(_consumed_states.items()):
        if expiry < now:
            del _consumed_states[key]
    if state in _consumed_states:
        return False
    _consumed_states[state] = now + STATE_MAX_AGE
    return True


def _state_allowed(state: str, cookie_value: str) -> bool:
    """Decide whether a callback state is acceptable.

    - The state must carry a valid, unexpired signature and be unused.
    - Normally it must also appear in the state cookie (CSRF binding).
      The cookie keeps the last few states so a second sign-in click
      doesn't invalidate a pending authorize window.
    - When the cookie is ABSENT entirely we accept the state anyway:
      the desktop Discord app opens the callback in the system default
      browser, which may not be the one the user clicked in. Signature,
      TTL, and single-use still bound the risk.
    """
    if not state or not _verify_state(state) or not _consume_state(state):
        return False
    if not cookie_value:
        return True  # cross-browser desktop app flow
    return state in cookie_value.split("|")


# Deep-link scheme handled by the Discord mobile app — opens the authorize
# screen in the app instead of a browser login wall.
APP_AUTHORIZE_URL = "discord://-/oauth2/authorize"


@router.get("/discord/login")
async def discord_login(request: Request, format: str = ""):
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

    if format == "json":
        # The SPA uses this on mobile: try the app deep link first,
        # fall back to the browser URL. State cookie set either way.
        from fastapi.responses import JSONResponse

        response: JSONResponse | RedirectResponse = JSONResponse({
            "web_url": f"{AUTHORIZE_URL}?{params}",
            "app_url": f"{APP_AUTHORIZE_URL}?{params}",
        })
    else:
        response = RedirectResponse(f"{AUTHORIZE_URL}?{params}", status_code=307)

    # Keep the last few states so concurrent sign-in attempts (second
    # click, prefetch refresh) don't orphan a pending authorize window.
    previous = request.cookies.get(OAUTH_STATE_COOKIE, "")
    recent = [state] + [s for s in previous.split("|") if s][:2]
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        "|".join(recent),
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
    if not _state_allowed(state, cookie_state):
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
