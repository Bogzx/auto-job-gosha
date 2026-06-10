"""Tests for the multi-channel delivery system."""

from __future__ import annotations

from datetime import datetime, time, timezone
from unittest.mock import MagicMock

import pytest

from gosha.delivery import (
    ChannelRegistry,
    DeliveryChannel,
    DeliveryPayload,
    DeliveryPreference,
    DiscordDMChannel,
    EmailChannel,
    WebhookChannel,
)
from gosha.models import Job, UserJob

# ── Test helpers ──────────────────────────────────────────────────────


def _make_payload(title: str = "Test Dev", company: str = "TestCo") -> DeliveryPayload:
    job = Job(
        url="https://test.com/job/1",
        title=title,
        company=company,
        location="Cluj",
        description="Test job description",
        source="indeed",
    )
    # Simulate an ID
    job.id = 1
    uj = UserJob(user_id=1, job_id=1, relevance_score=0.85)
    uj.id = 42
    return DeliveryPayload(
        job=job,
        user_job=uj,
        relevance_score=0.85,
        subscription_keywords=["developer"],
    )


class MockChannel(DeliveryChannel):
    """A mock delivery channel for testing."""

    def __init__(self, name: str = "mock", should_fail: bool = False):
        self._name = name
        self._should_fail = should_fail
        self.sent: list[tuple[DeliveryPayload, str]] = []

    @property
    def name(self) -> str:
        return self._name

    async def send(self, payload: DeliveryPayload, target: str) -> bool:
        if self._should_fail:
            return False
        self.sent.append((payload, target))
        return True


# ── DeliveryPayload ───────────────────────────────────────────────────


class TestDeliveryPayload:
    def test_creation(self):
        payload = _make_payload()
        assert payload.job.title == "Test Dev"
        assert payload.relevance_score == 0.85
        assert payload.subscription_keywords == ["developer"]


# ── DeliveryPreference ────────────────────────────────────────────────


class TestDeliveryPreference:
    def test_defaults(self):
        pref = DeliveryPreference()
        assert pref.channel == "discord_dm"
        assert pref.mode == "instant"
        assert pref.max_per_day == 50

    def test_quiet_hours_normal(self):
        pref = DeliveryPreference(
            quiet_start=time(23, 0),
            quiet_end=time(8, 0),
        )
        # 2am should be quiet
        at_2am = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
        assert pref.is_quiet_time(at_2am) is True

        # 10am should not be quiet
        at_10am = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        assert pref.is_quiet_time(at_10am) is False

    def test_quiet_hours_same_day(self):
        pref = DeliveryPreference(
            quiet_start=time(12, 0),
            quiet_end=time(14, 0),
        )
        # 1pm should be quiet
        at_1pm = datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)
        assert pref.is_quiet_time(at_1pm) is True

        # 3pm should not be quiet
        at_3pm = datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)
        assert pref.is_quiet_time(at_3pm) is False

    def test_no_quiet_hours(self):
        pref = DeliveryPreference()
        assert pref.is_quiet_time() is False


# ── MockChannel ───────────────────────────────────────────────────────


class TestMockChannel:
    @pytest.mark.asyncio
    async def test_send(self):
        channel = MockChannel()
        payload = _make_payload()
        result = await channel.send(payload, "user123")
        assert result is True
        assert len(channel.sent) == 1

    @pytest.mark.asyncio
    async def test_send_failure(self):
        channel = MockChannel(should_fail=True)
        payload = _make_payload()
        result = await channel.send(payload, "user123")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_batch(self):
        channel = MockChannel()
        payloads = [_make_payload(f"Job {i}") for i in range(5)]
        sent = await channel.send_batch(payloads, "user123")
        assert sent == 5
        assert len(channel.sent) == 5


# ── ChannelRegistry ──────────────────────────────────────────────────


class TestChannelRegistry:
    def test_register_and_get(self):
        registry = ChannelRegistry()
        channel = MockChannel("test_channel")
        registry.register(channel)
        assert registry.get("test_channel") is channel
        assert registry.get("nonexistent") is None

    def test_available_channels(self):
        registry = ChannelRegistry()
        registry.register(MockChannel("ch1"))
        registry.register(MockChannel("ch2"))
        assert sorted(registry.available_channels) == ["ch1", "ch2"]

    @pytest.mark.asyncio
    async def test_deliver_instant(self):
        registry = ChannelRegistry()
        channel = MockChannel("discord_dm")
        registry.register(channel)

        pref = DeliveryPreference(channel="discord_dm", target="12345", mode="instant")
        payloads = [_make_payload()]
        sent = await registry.deliver(pref, payloads)
        assert sent == 1

    @pytest.mark.asyncio
    async def test_deliver_quiet_hours(self):
        registry = ChannelRegistry()
        channel = MockChannel("discord_dm")
        registry.register(channel)

        pref = DeliveryPreference(
            channel="discord_dm",
            target="12345",
            quiet_start=time(0, 0),
            quiet_end=time(23, 59),
        )
        payloads = [_make_payload()]
        sent = await registry.deliver(pref, payloads)
        assert sent == 0  # Quiet hours active

    @pytest.mark.asyncio
    async def test_deliver_max_per_day(self):
        registry = ChannelRegistry()
        channel = MockChannel("discord_dm")
        registry.register(channel)

        pref = DeliveryPreference(
            channel="discord_dm",
            target="12345",
            max_per_day=3,
        )
        payloads = [_make_payload(f"Job {i}") for i in range(10)]
        sent = await registry.deliver(pref, payloads)
        assert sent == 3

    @pytest.mark.asyncio
    async def test_deliver_unknown_channel(self):
        registry = ChannelRegistry()
        pref = DeliveryPreference(channel="nonexistent", target="x")
        sent = await registry.deliver(pref, [_make_payload()])
        assert sent == 0


# ── EmailChannel ──────────────────────────────────────────────────────


class TestEmailChannel:
    def test_name(self):
        ch = EmailChannel()
        assert ch.name == "email"

    @pytest.mark.asyncio
    async def test_send_no_config(self):
        ch = EmailChannel()  # No SMTP configured
        payload = _make_payload()
        result = await ch.send(payload, "test@example.com")
        assert result is False


# ── WebhookChannel ────────────────────────────────────────────────────


class TestWebhookChannel:
    def test_name(self):
        ch = WebhookChannel()
        assert ch.name == "webhook"


# ── DiscordDMChannel ──────────────────────────────────────────────────


class TestDiscordDMChannel:
    def test_name(self):
        mock_bot = MagicMock()
        ch = DiscordDMChannel(mock_bot)
        assert ch.name == "discord_dm"
