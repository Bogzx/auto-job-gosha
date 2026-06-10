"""Tests for web settings loading."""

from __future__ import annotations

import pytest

from gosha.config import load_web_settings


def _set_required(monkeypatch) -> None:
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "123")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "abc")


def test_web_settings_defaults(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("DISCORD_REDIRECT_URI", raising=False)
    ws = load_web_settings()
    assert ws.session_secret == "test-secret"
    assert ws.discord_client_id == "123"
    assert ws.discord_client_secret == "abc"
    assert ws.redirect_uri == "http://localhost:8000/api/v1/auth/discord/callback"
    assert ws.cookie_secure is False


def test_web_settings_prod(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://jobs.bogdantruta.com")
    monkeypatch.delenv("DISCORD_REDIRECT_URI", raising=False)
    ws = load_web_settings()
    assert ws.redirect_uri == (
        "https://jobs.bogdantruta.com/api/v1/auth/discord/callback"
    )
    assert ws.cookie_secure is True


def test_web_settings_explicit_redirect(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://other.example/cb")
    ws = load_web_settings()
    assert ws.redirect_uri == "https://other.example/cb"


def test_web_settings_optional_fields(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("DISCORD_GUILD_ID", "999888")
    monkeypatch.setenv("DISCORD_INVITE_URL", "https://discord.gg/abc")
    ws = load_web_settings()
    assert ws.guild_id == 999888
    assert ws.invite_url == "https://discord.gg/abc"


def test_web_settings_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setenv("DISCORD_CLIENT_ID", "1")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "x")
    with pytest.raises(RuntimeError):
        load_web_settings()
