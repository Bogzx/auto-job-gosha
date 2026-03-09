"""Wrapper around JobSpy that routes requests through a random SOCKS5 tunnel."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from functools import partial
from typing import TYPE_CHECKING

import pandas as pd
from jobspy import scrape_jobs

if TYPE_CHECKING:
    from ssh_tunnels import SSHTunnelManager

log = logging.getLogger(__name__)

# ── Keyword expansion ──────────────────────────────────────────────
# Broad user-facing terms → specific job board search queries.

KEYWORD_EXPANSIONS: dict[str, list[str]] = {
    "computer science internship": [
        "software engineer intern",
        "software developer intern",
        "web developer intern",
        "data scientist intern",
        "data analyst intern",
        "data engineer intern",
        "machine learning intern",
        "AI intern",
        "backend developer intern",
        "frontend developer intern",
        "full stack intern",
        "devops intern",
        "cloud engineer intern",
        "cybersecurity intern",
        "IT intern",
        "QA intern",
        "computer science intern",
        "junior developer",
        "internship",
    ],
    "computer science": [
        "software engineer",
        "software developer",
        "web developer",
        "data scientist",
        "data analyst",
        "data engineer",
        "machine learning engineer",
        "AI engineer",
        "backend developer",
        "frontend developer",
        "full stack developer",
        "devops engineer",
        "cloud engineer",
        "cybersecurity analyst",
        "systems administrator",
        "QA engineer",
        "junior developer",
        "graduate software",
    ],
    "cs entry level": [
        "junior software engineer",
        "junior developer",
        "junior data analyst",
        "entry level software",
        "entry level developer",
        "entry level data",
        "graduate software engineer",
        "graduate developer",
        "trainee developer",
        "trainee software",
        "associate software engineer",
    ],
    "tech internship": [
        "software engineer intern",
        "data analyst intern",
        "IT intern",
        "devops intern",
        "cloud intern",
        "cybersecurity intern",
        "product manager intern",
        "UX designer intern",
        "tech intern",
    ],
    "data science": [
        "data scientist",
        "data analyst",
        "machine learning engineer",
        "data engineer",
        "business intelligence analyst",
        "AI engineer",
        "NLP engineer",
        "statistician",
    ],
    "software engineering": [
        "software engineer",
        "software developer",
        "backend developer",
        "frontend developer",
        "full stack developer",
        "mobile developer",
        "platform engineer",
        "web developer",
        "application developer",
    ],
}

# ── Location aliases ───────────────────────────────────────────────
# Maps short/informal location names to the canonical form for searching,
# plus a list of substrings used for fuzzy-matching results.

LOCATION_ALIASES: dict[str, dict] = {
    "cluj": {"search": "Cluj-Napoca, Romania", "match": ["cluj"]},
    "cluj napoca": {"search": "Cluj-Napoca, Romania", "match": ["cluj"]},
    "cluj-napoca": {"search": "Cluj-Napoca, Romania", "match": ["cluj"]},
    "bucharest": {"search": "Bucharest, Romania", "match": ["bucharest", "bucuresti", "bucurești"]},
    "bucuresti": {"search": "Bucharest, Romania", "match": ["bucharest", "bucuresti", "bucurești"]},
    "timisoara": {"search": "Timisoara, Romania", "match": ["timisoara", "timișoara"]},
    "iasi": {"search": "Iasi, Romania", "match": ["iasi", "iași"]},
    "brasov": {"search": "Brasov, Romania", "match": ["brasov", "brașov"]},
    "sibiu": {"search": "Sibiu, Romania", "match": ["sibiu"]},
    "craiova": {"search": "Craiova, Romania", "match": ["craiova"]},
    "constanta": {"search": "Constanta, Romania", "match": ["constanta", "constanța"]},
    "oradea": {"search": "Oradea, Romania", "match": ["oradea"]},
    "dublin": {"search": "Dublin, Ireland", "match": ["dublin"]},
    "london": {"search": "London, United Kingdom", "match": ["london"]},
    "berlin": {"search": "Berlin, Germany", "match": ["berlin"]},
    "amsterdam": {"search": "Amsterdam, Netherlands", "match": ["amsterdam"]},
    "romania": {"search": "Romania", "match": ["romania", "bucharest", "cluj", "timisoara", "iasi", "brasov"]},
}


def normalize_location(location: str) -> tuple[str, list[str]]:
    """Return (search_location, match_substrings) for a user-provided location.

    If the location is in LOCATION_ALIASES, return the canonical search form
    and fuzzy match substrings. Otherwise return the location as-is.
    """
    normalized = location.lower().strip()
    alias = LOCATION_ALIASES.get(normalized)
    if alias:
        return alias["search"], alias["match"]
    # Default: search as-is, match by substring
    return location, [normalized]


def expand_keyword(keyword: str) -> list[str]:
    """Return a list of specific search terms for a keyword."""
    normalized = keyword.lower().strip()
    return KEYWORD_EXPANSIONS.get(normalized, [keyword])


def location_matches(job_location: str, match_substrings: list[str]) -> bool:
    """Check if a job's location fuzzy-matches any of the expected substrings."""
    if not job_location or job_location == "nan":
        return True  # If no location data, include it rather than miss it
    loc_lower = job_location.lower()
    return any(sub in loc_lower for sub in match_substrings)


# ── Title relevance filtering ─────────────────────────────────────
# After scraping, filter out jobs whose titles don't match the
# expected seniority level and/or domain for the subscription.

_ENTRY_LEVEL_RE = re.compile(
    r"(?i)\b(?:intern(?:ship)?|junior|jr\.?|graduate|grad\b|entry.?level|"
    r"trainee|academy|apprentice|placement|co.?op|summer)"
)

_SENIOR_RE = re.compile(
    r"(?i)\b(?:senior|sr\.?|lead|principal|staff|director|"
    r"manager|head\b|vp|chief|architect)\b"
)

_TECH_RE = re.compile(
    r"(?i)\b(?:software|developer|develop(?:ment|er)|engineer(?:ing)?|"
    r"programm(?:er|ing)|coder|coding|"
    r"data|machine.?learning|\bml\b|\bai\b|deep.?learning|\bnlp\b|"
    r"devops|dev.?ops|cloud|cyber|security|"
    r"front.?end|back.?end|full.?stack|"
    r"web|python|java|javascript|typescript|\.net|c\+\+|c#|ruby|golang|rust|kotlin|swift|"
    r"\bqa\b|\bsdet\b|test.?auto|quality.?assur|"
    r"\bsql\b|database|\bdba\b|"
    r"network|\bsre\b|site.?reliab|infrastructure|"
    r"mobile|\bios\b|android|flutter|react|angular|vue|"
    r"tech(?:nolog)?|computer|comput|informatic)\b"
)


def _keyword_wants_entry_level(keyword: str) -> bool:
    """Check if the subscription keyword implies entry-level/intern jobs."""
    kw = keyword.lower()
    return any(w in kw for w in ("intern", "entry", "junior", "graduate", "trainee"))


def _keyword_wants_tech(keyword: str) -> bool:
    """Check if the subscription keyword implies tech/CS domain."""
    kw = keyword.lower().strip()
    # All our expansion categories are tech-related
    if kw in KEYWORD_EXPANSIONS:
        return True
    return any(w in kw for w in (
        "computer", "software", "tech", "data", "engineer",
        "developer", "devops", "cyber", "cloud", "ml", "ai",
    ))


def _filter_by_relevance(df: pd.DataFrame, keyword: str) -> pd.DataFrame:
    """Filter results by title relevance to the subscription keyword.

    - If keyword implies entry-level: title must have an entry-level indicator
      and must NOT have a senior-level indicator.
    - If keyword implies tech: title must contain a tech-related term.
    """
    if df.empty or "title" not in df.columns:
        return df

    want_entry = _keyword_wants_entry_level(keyword)
    want_tech = _keyword_wants_tech(keyword)

    if not want_entry and not want_tech:
        return df  # No filtering for generic keywords

    def is_relevant(title: str) -> bool:
        if not title or title == "nan":
            return False
        if want_entry:
            if not _ENTRY_LEVEL_RE.search(title):
                return False
            if _SENIOR_RE.search(title):
                return False
        if want_tech:
            if not _TECH_RE.search(title):
                return False
        return True

    before = len(df)
    filtered = df[df["title"].apply(lambda t: is_relevant(str(t)))]
    removed = before - len(filtered)
    if removed > 0:
        log.info("Relevance filter: %d → %d results (removed %d irrelevant for '%s')",
                 before, len(filtered), removed, keyword)
    return filtered


def _city_only(location: str) -> str:
    """Strip the country part from 'City, Country' for Glassdoor compatibility."""
    return location.split(",")[0].strip()


async def _scrape_single(
    tunnel_manager: SSHTunnelManager,
    search_term: str,
    location: str,
    max_age_days: int,
) -> pd.DataFrame:
    """Run one JobSpy scrape through a randomly chosen active proxy.

    Indeed/LinkedIn get the full location; Glassdoor gets city-only
    (it fails to parse 'City, Country' format).
    """
    proxies = tunnel_manager.active_proxies()
    if not proxies:
        log.warning("No active proxies – skipping '%s' in '%s'", search_term, location)
        return pd.DataFrame()

    random.shuffle(proxies)
    gd_location = _city_only(location)

    last_error: Exception | None = None
    for proxy in proxies:
        try:
            log.info("Searching '%s' in '%s' (max_age=%dd) via %s", search_term, location, max_age_days, proxy)
            loop = asyncio.get_running_loop()

            # Indeed + LinkedIn with full location
            df_main: pd.DataFrame = await loop.run_in_executor(
                None,
                partial(
                    scrape_jobs,
                    site_name=["indeed", "linkedin"],
                    search_term=search_term,
                    location=location,
                    results_wanted=30,
                    hours_old=max_age_days * 24,
                    proxy=proxy,
                ),
            )

            # Glassdoor with city-only location
            try:
                df_gd: pd.DataFrame = await loop.run_in_executor(
                    None,
                    partial(
                        scrape_jobs,
                        site_name=["glassdoor"],
                        search_term=search_term,
                        location=gd_location,
                        results_wanted=30,
                        hours_old=max_age_days * 24,
                        proxy=proxy,
                    ),
                )
            except Exception as gd_exc:
                log.warning("Glassdoor failed for '%s' in '%s': %s", search_term, gd_location, gd_exc)
                df_gd = pd.DataFrame()

            df = pd.concat([df_main, df_gd], ignore_index=True) if not df_gd.empty else df_main
            log.info("Found %d results for '%s' in '%s'", len(df), search_term, location)
            return df
        except Exception as exc:
            log.error("Proxy %s failed for '%s': %s", proxy, search_term, exc)
            last_error = exc

    log.error("All proxies failed for '%s' in '%s'. Last error: %s", search_term, location, last_error)
    return pd.DataFrame()


async def search_jobs(
    tunnel_manager: SSHTunnelManager,
    keyword: str,
    location: str,
    max_age_days: int,
) -> pd.DataFrame:
    """Expand keyword, normalize location, scrape each term, and merge results.

    Returns a deduplicated DataFrame of job results (may be empty).
    """
    terms = expand_keyword(keyword)
    search_location, match_subs = normalize_location(location)
    log.info("Keyword '%s' → %d terms, location '%s' → '%s'", keyword, len(terms), location, search_location)

    all_frames: list[pd.DataFrame] = []
    for term in terms:
        df = await _scrape_single(tunnel_manager, term, search_location, max_age_days)
        if not df.empty:
            all_frames.append(df)
        # Small delay between searches to be polite to job boards
        await asyncio.sleep(2)

    if not all_frames:
        return pd.DataFrame()

    merged = pd.concat(all_frames, ignore_index=True)

    # Deduplicate by job URL
    url_col = "job_url" if "job_url" in merged.columns else "link"
    if url_col in merged.columns:
        merged = merged.drop_duplicates(subset=[url_col], keep="first")

    # Filter by fuzzy location match
    if "location" in merged.columns:
        before = len(merged)
        merged = merged[merged["location"].apply(lambda loc: location_matches(str(loc), match_subs))]
        log.info("Location filter: %d → %d results for '%s'", before, len(merged), location)

    # Filter by title relevance (seniority level + domain)
    merged = _filter_by_relevance(merged, keyword)

    log.info("Final: %d results for '%s' in '%s'", len(merged), keyword, location)
    return merged
