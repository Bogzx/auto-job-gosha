"""Discord OAuth2 authentication and session management."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

log = logging.getLogger(__name__)

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")

# Build redirect URI: explicit env var > derived from DOMAIN > localhost fallback
_domain = os.getenv("DOMAIN", "")
_default_redirect = f"https://{_domain}/callback" if _domain else "http://localhost:8080/callback"
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", _default_redirect)

DISCORD_API = "https://discord.com/api/v10"
DISCORD_OAUTH2_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = f"{DISCORD_API}/oauth2/token"
DISCORD_USER_URL = f"{DISCORD_API}/users/@me"


def oauth2_login_url() -> str | None:
    """Generate the Discord OAuth2 authorization URL."""
    if not DISCORD_CLIENT_ID:
        return None
    params = (
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify"
    )
    return DISCORD_OAUTH2_URL + params


async def oauth2_callback_handler(code: str) -> dict | None:
    """Exchange OAuth2 code for user data."""
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        return None

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            # Exchange code for token
            token_resp = await client.post(
                DISCORD_TOKEN_URL,
                data={
                    "client_id": DISCORD_CLIENT_ID,
                    "client_secret": DISCORD_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": DISCORD_REDIRECT_URI,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_resp.status_code != 200:
                log.error("OAuth2 token exchange failed: %s", token_resp.text)
                return None

            token_data = token_resp.json()
            access_token = token_data["access_token"]

            # Fetch user info
            user_resp = await client.get(
                DISCORD_USER_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if user_resp.status_code != 200:
                log.error("Failed to fetch Discord user: %s", user_resp.text)
                return None

            return user_resp.json()

    except ImportError:
        log.error("httpx not installed — OAuth2 unavailable")
        return None
    except Exception as exc:
        log.error("OAuth2 callback failed: %s", exc)
        return None


class SessionManager:
    """Simple HMAC-signed cookie session manager."""

    def __init__(self, secret_key: str, max_age: int = 86400 * 7) -> None:
        self._secret = secret_key.encode()
        self._max_age = max_age

    def create_session(self, discord_id: int, username: str) -> str:
        """Create a signed session token."""
        payload = json.dumps({
            "discord_id": discord_id,
            "username": username,
            "created_at": int(time.time()),
        }).encode()
        sig = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()
        encoded = urlsafe_b64encode(payload).decode()
        return f"{encoded}.{sig}"

    def get_session(self, token: str) -> dict | None:
        """Validate and decode a session token. Returns None if invalid."""
        if not token or "." not in token:
            return None
        try:
            encoded, sig = token.rsplit(".", 1)
            payload = urlsafe_b64decode(encoded)
            expected_sig = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected_sig):
                return None
            data = json.loads(payload)
            # Check expiry
            created = data.get("created_at", 0)
            if time.time() - created > self._max_age:
                return None
            return data
        except Exception:
            return None


SESSION_SECRET_DEFAULT = "change-me-in-production"

IS_PRODUCTION = bool(_domain)


def _check_session_secret() -> None:
    secret = os.getenv("SESSION_SECRET", SESSION_SECRET_DEFAULT)
    if secret == SESSION_SECRET_DEFAULT:
        log.warning(
            "SESSION_SECRET is set to the default value — sessions are NOT secure. "
            "Set a random SESSION_SECRET in your .env file."
        )


async def get_current_user(request: Any) -> dict | None:
    """FastAPI dependency to get current user from session cookie."""
    token = request.cookies.get("session", "")
    mgr = SessionManager(os.getenv("SESSION_SECRET", SESSION_SECRET_DEFAULT))
    return mgr.get_session(token)
