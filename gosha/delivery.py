"""Multi-channel delivery system.

Abstracts job notification delivery behind a common interface.
Each channel handles its own formatting and sending.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any

from gosha.models import Job, UserJob

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Delivery payload — channel-agnostic representation of what to deliver
# ---------------------------------------------------------------------------


@dataclass
class DeliveryPayload:
    """Channel-agnostic data bundle for a single job notification."""

    job: Job
    user_job: UserJob
    relevance_score: float | None = None
    subscription_keywords: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Abstract delivery channel
# ---------------------------------------------------------------------------


class DeliveryChannel(ABC):
    """Base class for all delivery channels."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name (e.g. 'discord_dm', 'email', 'webhook')."""
        ...

    @abstractmethod
    async def send(self, payload: DeliveryPayload, target: str) -> bool:
        """Send a single job notification.

        Args:
            payload: The job data to deliver.
            target: Channel-specific target (Discord user ID, email, webhook URL).

        Returns:
            True if delivery succeeded.
        """
        ...

    async def send_batch(
        self, payloads: list[DeliveryPayload], target: str
    ) -> int:
        """Send multiple job notifications. Default: send one by one.

        Override for channels that support digest mode.
        Returns number of successful deliveries.
        """
        sent = 0
        for payload in payloads:
            if await self.send(payload, target):
                sent += 1
        return sent


# ---------------------------------------------------------------------------
# Discord DM channel
# ---------------------------------------------------------------------------


class DiscordDMChannel(DeliveryChannel):
    """Delivers job notifications via Discord direct messages."""

    def __init__(self, bot: Any) -> None:
        self._bot = bot

    @property
    def name(self) -> str:
        return "discord_dm"

    async def send(self, payload: DeliveryPayload, target: str) -> bool:
        import discord
        from gosha.views import build_job_embed_with_buttons

        discord_id = int(target)
        try:
            user = self._bot.get_user(discord_id)
            if user is None:
                user = await self._bot.fetch_user(discord_id)
            dm = await user.create_dm()

            embed, view = build_job_embed_with_buttons(
                payload.job,
                payload.user_job.id,
                payload.relevance_score,
            )
            await dm.send(embed=embed, view=view)
            return True

        except discord.Forbidden:
            log.warning("Cannot DM user %d — DMs are closed", discord_id)
            return False
        except discord.HTTPException as exc:
            log.error("Failed to DM user %d: %s", discord_id, exc)
            return False

    async def send_batch(
        self, payloads: list[DeliveryPayload], target: str
    ) -> int:
        """Send jobs one at a time with feedback buttons."""
        sent = 0
        for payload in payloads:
            if await self.send(payload, target):
                sent += 1
            # Small delay to avoid rate limits
            await asyncio.sleep(0.5)
        return sent


# ---------------------------------------------------------------------------
# Email digest channel
# ---------------------------------------------------------------------------


class EmailChannel(DeliveryChannel):
    """Delivers job notifications via email (digest mode)."""

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        from_address: str = "",
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_user = smtp_user
        self._smtp_password = smtp_password
        self._from_address = from_address

    @property
    def name(self) -> str:
        return "email"

    async def send(self, payload: DeliveryPayload, target: str) -> bool:
        """Send a single job notification email."""
        return await self._send_email(
            to_address=target,
            subject=f"New job match: {payload.job.title} at {payload.job.company}",
            body=self._format_single(payload),
        )

    async def send_batch(
        self, payloads: list[DeliveryPayload], target: str
    ) -> int:
        """Send a digest email with all matched jobs."""
        if not payloads:
            return 0

        body = self._format_digest(payloads)
        success = await self._send_email(
            to_address=target,
            subject=f"Job digest: {len(payloads)} new matches",
            body=body,
        )
        return len(payloads) if success else 0

    def _format_single(self, payload: DeliveryPayload) -> str:
        j = payload.job
        lines = [
            f"<h2><a href='{j.url}'>{j.title}</a></h2>",
            f"<p><strong>Company:</strong> {j.company}</p>",
            f"<p><strong>Location:</strong> {j.location}</p>",
        ]
        if j.salary_min or j.salary_max:
            parts = []
            if j.salary_min:
                parts.append(f"{j.salary_min:,.0f}")
            if j.salary_max:
                parts.append(f"{j.salary_max:,.0f}")
            salary = " - ".join(parts)
            if j.salary_currency:
                salary += f" {j.salary_currency}"
            lines.append(f"<p><strong>Salary:</strong> {salary}</p>")
        if j.description:
            desc = j.description[:300] + "..." if len(j.description) > 300 else j.description
            lines.append(f"<p>{desc}</p>")
        return "\n".join(lines)

    def _format_digest(self, payloads: list[DeliveryPayload]) -> str:
        parts = [f"<h1>{len(payloads)} New Job Matches</h1>", "<hr>"]
        for payload in payloads:
            parts.append(self._format_single(payload))
            parts.append("<hr>")
        return "\n".join(parts)

    async def _send_email(
        self, to_address: str, subject: str, body: str
    ) -> bool:
        if not self._smtp_host:
            log.warning("Email delivery not configured (no SMTP host)")
            return False
        try:
            import aiosmtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart("alternative")
            msg["From"] = self._from_address
            msg["To"] = to_address
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html"))

            await aiosmtplib.send(
                msg,
                hostname=self._smtp_host,
                port=self._smtp_port,
                username=self._smtp_user,
                password=self._smtp_password,
                use_tls=True,
            )
            return True
        except ImportError:
            log.warning("aiosmtplib not installed — email delivery unavailable")
            return False
        except Exception as exc:
            log.error("Email delivery failed to %s: %s", to_address, exc)
            return False


# ---------------------------------------------------------------------------
# Webhook channel
# ---------------------------------------------------------------------------


class WebhookChannel(DeliveryChannel):
    """Delivers job notifications via HTTP webhook (POST)."""

    @property
    def name(self) -> str:
        return "webhook"

    async def send(self, payload: DeliveryPayload, target: str) -> bool:
        try:
            import aiohttp

            j = payload.job
            data = {
                "event": "job_match",
                "job": {
                    "url": j.url,
                    "title": j.title,
                    "company": j.company,
                    "location": j.location,
                    "description": (j.description or "")[:500],
                    "salary_min": j.salary_min,
                    "salary_max": j.salary_max,
                    "salary_currency": j.salary_currency,
                    "source": j.source,
                },
                "score": payload.relevance_score,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    target,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status < 300:
                        return True
                    log.warning("Webhook %s returned %d", target, resp.status)
                    return False
        except ImportError:
            log.warning("aiohttp not installed — webhook delivery unavailable")
            return False
        except Exception as exc:
            log.error("Webhook delivery to %s failed: %s", target, exc)
            return False


# ---------------------------------------------------------------------------
# Delivery preferences
# ---------------------------------------------------------------------------


@dataclass
class DeliveryPreference:
    """Per-user delivery configuration."""

    channel: str = "discord_dm"  # discord_dm, email, webhook
    target: str = ""  # Discord ID, email address, or webhook URL
    mode: str = "instant"  # instant or digest
    quiet_start: time | None = None  # Don't deliver after this time
    quiet_end: time | None = None  # Resume delivery at this time
    max_per_day: int = 50

    def is_quiet_time(self, now: datetime | None = None) -> bool:
        """Check if current time falls within quiet hours."""
        if self.quiet_start is None or self.quiet_end is None:
            return False
        if now is None:
            now = datetime.now(timezone.utc)
        current_time = now.time()
        if self.quiet_start <= self.quiet_end:
            return self.quiet_start <= current_time <= self.quiet_end
        else:  # Spans midnight (e.g., 23:00 - 08:00)
            return current_time >= self.quiet_start or current_time <= self.quiet_end


# ---------------------------------------------------------------------------
# Channel registry
# ---------------------------------------------------------------------------


class ChannelRegistry:
    """Registry of available delivery channels."""

    def __init__(self) -> None:
        self._channels: dict[str, DeliveryChannel] = {}

    def register(self, channel: DeliveryChannel) -> None:
        self._channels[channel.name] = channel

    def get(self, name: str) -> DeliveryChannel | None:
        return self._channels.get(name)

    @property
    def available_channels(self) -> list[str]:
        return list(self._channels.keys())

    async def deliver(
        self,
        preference: DeliveryPreference,
        payloads: list[DeliveryPayload],
    ) -> int:
        """Deliver payloads using the user's preferred channel and mode."""
        channel = self.get(preference.channel)
        if channel is None:
            log.error("Unknown delivery channel: %s", preference.channel)
            return 0

        if preference.is_quiet_time():
            log.info("Skipping delivery — quiet hours active for %s", preference.target)
            return 0

        # Apply max_per_day limit
        payloads = payloads[: preference.max_per_day]

        if preference.mode == "digest":
            return await channel.send_batch(payloads, preference.target)
        else:
            return await channel.send_batch(payloads, preference.target)
