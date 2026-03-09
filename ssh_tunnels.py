"""Manage background SSH SOCKS5 tunnel processes."""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field

from config import VPSConfig

log = logging.getLogger(__name__)


@dataclass
class _Tunnel:
    """Internal bookkeeping for a single tunnel."""

    vps: VPSConfig
    process: asyncio.subprocess.Process | None = None


class SSHTunnelManager:
    """Spin up / tear down SSH dynamic-port-forwarding tunnels."""

    def __init__(self, vps_list: list[VPSConfig]) -> None:
        self._tunnels: list[_Tunnel] = [_Tunnel(vps=v) for v in vps_list]

    # ── public API ──────────────────────────────────────────────

    async def start_all(self) -> None:
        """Open an SSH SOCKS5 tunnel for every configured VPS."""
        ssh_bin = shutil.which("ssh")
        if ssh_bin is None:
            raise RuntimeError("ssh binary not found – install openssh-client")

        for t in self._tunnels:
            cmd = [
                ssh_bin,
                "-i", t.vps.key_path,
                "-D", str(t.vps.local_port),
                "-N",                         # no remote command
                "-q",                          # quiet
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3",
                "-o", "ExitOnForwardFailure=yes",
                f"{t.vps.user}@{t.vps.host}",
            ]
            log.info("Opening tunnel  %s@%s → 127.0.0.1:%d", t.vps.user, t.vps.host, t.vps.local_port)
            t.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            # Give SSH a moment to bind the port
            await asyncio.sleep(1)
            if t.process.returncode is not None:
                stderr = (await t.process.stderr.read()).decode() if t.process.stderr else ""
                log.error("Tunnel to %s exited immediately: %s", t.vps.host, stderr)
                t.process = None
            else:
                log.info("Tunnel active on 127.0.0.1:%d", t.vps.local_port)

    async def stop_all(self) -> None:
        """Terminate every running tunnel process."""
        for t in self._tunnels:
            if t.process and t.process.returncode is None:
                log.info("Closing tunnel 127.0.0.1:%d", t.vps.local_port)
                t.process.terminate()
                try:
                    await asyncio.wait_for(t.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    t.process.kill()
                t.process = None

    def active_proxies(self) -> list[str]:
        """Return SOCKS5 proxy URLs for all currently alive tunnels."""
        proxies: list[str] = []
        for t in self._tunnels:
            if t.process and t.process.returncode is None:
                proxies.append(f"socks5://127.0.0.1:{t.vps.local_port}")
        return proxies
