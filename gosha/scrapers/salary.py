"""Salary string parsing for Romanian job boards.

Boards quote monthly figures as free text: "5000 - 10000 RON",
"900 - 1250" (currency implied by the board), "3500 RON".
"""

from __future__ import annotations

import re

_RANGE_RE = re.compile(
    r"(\d[\d.,\s]*)\s*(?:-|–|—|to)\s*(\d[\d.,\s]*)\s*([A-Za-z]{3})?"
)
_SINGLE_RE = re.compile(r"(\d[\d.,\s]*)\s*([A-Za-z]{3})?")

_KNOWN_CURRENCIES = {"RON", "EUR", "USD", "GBP", "LEI"}


def _to_number(raw: str) -> float | None:
    """'1.500' / '1,500' / '1 500' -> 1500.0 (separators are thousands)."""
    digits = re.sub(r"[^\d]", "", raw)
    return float(digits) if digits else None


def _normalize_currency(raw: str | None, default: str | None) -> str | None:
    if raw:
        cur = raw.upper()
        if cur == "LEI":
            cur = "RON"
        if cur in _KNOWN_CURRENCIES:
            return cur
    return default


def parse_salary_range(
    text: str | None, default_currency: str | None = None,
) -> tuple[float | None, float | None, str | None]:
    """Parse a salary string into (min, max, currency); Nones when absent."""
    if not text or not text.strip():
        return None, None, None

    match = _RANGE_RE.search(text)
    if match:
        low = _to_number(match.group(1))
        high = _to_number(match.group(2))
        currency = _normalize_currency(match.group(3), default_currency)
        return low, high, currency

    match = _SINGLE_RE.search(text)
    if match:
        value = _to_number(match.group(1))
        if value is None:
            return None, None, None
        currency = _normalize_currency(match.group(2), default_currency)
        return value, value, currency

    return None, None, None
