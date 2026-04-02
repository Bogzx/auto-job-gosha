"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env file from project root (no-op if it doesn't exist)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


@dataclass(frozen=True)
class VPSConfig:
    """Connection details for a single proxy VPS."""

    host: str
    user: str
    local_port: int
    key_path: str = "/root/.ssh/id_rsa"


@dataclass(frozen=True)
class Settings:
    """Application-wide settings populated from environment variables."""

    discord_token: str
    database_url: str
    vps_list: list[VPSConfig] = field(default_factory=list)

    # Scheduler
    scrape_interval_minutes: int = 60

    # Discord channel where job alerts are posted
    alert_channel_id: int = 0

    # Matching
    use_semantic_matching: bool = False
    semantic_model: str = "all-MiniLM-L6-v2"
    semantic_threshold: float = 0.40


def _parse_vps_list() -> list[VPSConfig]:
    """Parse VPS_* env vars into a list of VPSConfig."""
    global_key = os.getenv("SSH_KEY_PATH", "/root/.ssh/id_rsa")
    configs: list[VPSConfig] = []
    for i in range(1, 10):
        host = os.getenv(f"VPS_{i}_HOST")
        if not host:
            continue
        user = os.getenv(f"VPS_{i}_USER", "ubuntu")
        local_port = int(os.getenv(f"VPS_{i}_PORT", str(1079 + i)))
        key_path = os.getenv(f"VPS_{i}_KEY", global_key)
        configs.append(
            VPSConfig(host=host, user=user, local_port=local_port, key_path=key_path)
        )
    return configs


def load_settings() -> Settings:
    """Build a Settings object from the current environment."""
    token = os.environ["DISCORD_TOKEN"]
    db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/jobs.db")
    alert_channel = int(os.getenv("ALERT_CHANNEL_ID", "0"))
    interval = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "60"))
    use_semantic = os.getenv("USE_SEMANTIC_MATCHING", "false").lower() == "true"
    semantic_model = os.getenv("SEMANTIC_MODEL", "all-MiniLM-L6-v2")
    semantic_threshold = float(os.getenv("SEMANTIC_THRESHOLD", "0.40"))

    return Settings(
        discord_token=token,
        database_url=db_url,
        vps_list=_parse_vps_list(),
        scrape_interval_minutes=interval,
        alert_channel_id=alert_channel,
        use_semantic_matching=use_semantic,
        semantic_model=semantic_model,
        semantic_threshold=semantic_threshold,
    )
