"""Adapter registry. These sources are additive: they run for every active
subscription regardless of its `boards` list (no proxies needed, cheap)."""

from __future__ import annotations

from gosha.scrapers.base import BaseScraper
from gosha.scrapers.bestjobs import BestJobsScraper
from gosha.scrapers.ejobs import EjobsScraper
from gosha.scrapers.hipo import HipoScraper
from gosha.scrapers.remoteok import RemoteOKScraper


def get_extra_scrapers() -> list[BaseScraper]:
    return [
        EjobsScraper(),
        BestJobsScraper(),
        HipoScraper(),
        RemoteOKScraper(),
    ]
