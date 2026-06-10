"""Tests for the switchable LLM provider (Gemini <-> OpenRouter)."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

import gosha.cover_letter as cl

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


@pytest.mark.asyncio
@respx.mock
async def test_openrouter_used_when_key_set(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    route = respx.post(OPENROUTER_URL).mock(
        return_value=Response(200, json={
            "choices": [{"message": {"content": "Generated letter."}}]
        })
    )

    result = await cl._call_llm("Write a letter")
    assert result == "Generated letter."

    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer or-key"
    body = json.loads(request.content)
    assert body["model"] == "deepseek/deepseek-v4-flash"
    assert body["messages"][0]["content"] == "Write a letter"


@pytest.mark.asyncio
async def test_gemini_used_without_openrouter_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    called = {}

    async def fake_gemini(prompt: str) -> str:
        called["prompt"] = prompt
        return "From Gemini"

    monkeypatch.setattr(cl, "_call_gemini", fake_gemini)
    result = await cl._call_llm("Hello")
    assert result == "From Gemini"
    assert called["prompt"] == "Hello"


@pytest.mark.asyncio
async def test_explicit_provider_overrides_autodetect(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    async def fake_gemini(prompt: str) -> str:
        return "Gemini wins"

    monkeypatch.setattr(cl, "_call_gemini", fake_gemini)
    assert await cl._call_llm("x") == "Gemini wins"


@pytest.mark.asyncio
@respx.mock
async def test_openrouter_error_returns_none(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    respx.post(OPENROUTER_URL).mock(return_value=Response(500, text="boom"))

    assert await cl._call_openrouter("x") is None
