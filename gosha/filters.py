"""Filtering and relevance logic for job matching.

All filters are pure functions that operate on individual job dicts or
DataFrames — no DB or IO dependencies.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

# ── Keyword expansion ─────────────────────────────────────────────────
# Broad user-facing terms -> specific job board search queries.

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


# ── Location aliases ──────────────────────────────────────────────────

LOCATION_ALIASES: dict[str, dict[str, Any]] = {
    "cluj": {"search": "Cluj-Napoca, Romania", "match": ["cluj"]},
    "cluj napoca": {"search": "Cluj-Napoca, Romania", "match": ["cluj"]},
    "cluj-napoca": {"search": "Cluj-Napoca, Romania", "match": ["cluj"]},
    "bucharest": {
        "search": "Bucharest, Romania",
        "match": ["bucharest", "bucuresti", "bucurești"],
    },
    "bucuresti": {
        "search": "Bucharest, Romania",
        "match": ["bucharest", "bucuresti", "bucurești"],
    },
    "timisoara": {
        "search": "Timisoara, Romania",
        "match": ["timisoara", "timișoara"],
    },
    "iasi": {"search": "Iasi, Romania", "match": ["iasi", "iași"]},
    "brasov": {"search": "Brasov, Romania", "match": ["brasov", "brașov"]},
    "sibiu": {"search": "Sibiu, Romania", "match": ["sibiu"]},
    "craiova": {"search": "Craiova, Romania", "match": ["craiova"]},
    "constanta": {
        "search": "Constanta, Romania",
        "match": ["constanta", "constanța"],
    },
    "oradea": {"search": "Oradea, Romania", "match": ["oradea"]},
    "dublin": {"search": "Dublin, Ireland", "match": ["dublin"]},
    "london": {"search": "London, United Kingdom", "match": ["london"]},
    "berlin": {"search": "Berlin, Germany", "match": ["berlin"]},
    "amsterdam": {"search": "Amsterdam, Netherlands", "match": ["amsterdam"]},
    "romania": {
        "search": "Romania",
        "match": ["romania", "bucharest", "cluj", "timisoara", "iasi", "brasov"],
    },
}

# ── Compiled regexes for title relevance ──────────────────────────────

ENTRY_LEVEL_RE = re.compile(
    r"(?i)\b(?:intern(?:ship)?|junior|jr\.?|graduate|grad\b|entry.?level|"
    r"trainee|academy|apprentice|placement|co.?op|summer)"
)

SENIOR_RE = re.compile(
    r"(?i)\b(?:senior|sr\.?|lead|principal|staff|director|"
    r"manager|head\b|vp|chief|architect)\b"
)

TECH_RE = re.compile(
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


# ── Pure functions ────────────────────────────────────────────────────


def normalize_location(location: str) -> tuple[str, list[str]]:
    """Return (search_location, match_substrings) for a user-provided location."""
    normalized = location.lower().strip()
    alias = LOCATION_ALIASES.get(normalized)
    if alias:
        return alias["search"], alias["match"]
    return location, [normalized]


def expand_keyword(keyword: str) -> list[str]:
    """Return a list of specific search terms for a broad keyword."""
    normalized = keyword.lower().strip()
    return KEYWORD_EXPANSIONS.get(normalized, [keyword])


def location_matches(job_location: str, match_substrings: list[str]) -> bool:
    """Check if a job's location fuzzy-matches any expected substrings."""
    if not job_location or pd.isna(job_location) or str(job_location).lower() == "nan":
        return True  # If no location data, include rather than miss
    loc_lower = str(job_location).lower()
    return any(sub in loc_lower for sub in match_substrings)


def keyword_wants_entry_level(keyword: str) -> bool:
    """Check if the subscription keyword implies entry-level/intern jobs."""
    kw = keyword.lower()
    return any(w in kw for w in ("intern", "entry", "junior", "graduate", "trainee"))


def keyword_wants_tech(keyword: str) -> bool:
    """Check if the subscription keyword implies tech/CS domain."""
    kw = keyword.lower().strip()
    if kw in KEYWORD_EXPANSIONS:
        return True
    return any(
        w in kw
        for w in (
            "computer", "software", "tech", "data", "engineer",
            "developer", "devops", "cyber", "cloud", "ml", "ai",
        )
    )


def title_is_relevant(title: str, keyword: str) -> bool:
    """Check if a job title is relevant for the given subscription keyword."""
    if not title or pd.isna(title):
        return False
    title = str(title)
    want_entry = keyword_wants_entry_level(keyword)
    want_tech = keyword_wants_tech(keyword)

    if not want_entry and not want_tech:
        return True  # No filtering for generic keywords

    if want_entry:
        if not ENTRY_LEVEL_RE.search(title):
            return False
        if SENIOR_RE.search(title):
            return False
    if want_tech:
        if not TECH_RE.search(title):
            return False
    return True


def matches_excluded_keywords(text: str, excluded: list[str]) -> bool:
    """Return True if text contains any of the excluded keywords."""
    if not excluded or not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in excluded)


def matches_company_blacklist(company: str, blacklist: list[str]) -> bool:
    """Return True if company is in the blacklist."""
    if not blacklist or not company:
        return False
    company_lower = company.lower().strip()
    return any(bl.lower().strip() == company_lower for bl in blacklist)


def matches_salary_minimum(
    salary_min_filter: int | None,
    job_salary_min: float | None,
    job_salary_max: float | None,
) -> bool:
    """Return True if the job meets the minimum salary requirement.

    If no salary data on the job, we include it (benefit of the doubt).
    """
    if salary_min_filter is None:
        return True
    if job_salary_max is not None:
        return job_salary_max >= salary_min_filter
    if job_salary_min is not None:
        return job_salary_min >= salary_min_filter
    return True  # No salary data — include


def matches_experience_level(title: str, levels: list[str]) -> bool:
    """Check if a job title matches the requested experience levels."""
    if not levels or "any" in levels:
        return True
    title_lower = str(title).lower() if title else ""

    for level in levels:
        level = level.lower()
        if level in ("intern", "internship"):
            if ENTRY_LEVEL_RE.search(title_lower):
                return True
        elif level == "junior":
            if re.search(r"\b(?:junior|jr\.?|entry.?level|graduate|trainee)\b", title_lower):
                return True
        elif level == "mid":
            # Mid-level: not entry-level and not senior
            if not ENTRY_LEVEL_RE.search(title_lower) and not SENIOR_RE.search(title_lower):
                return True
        elif level == "senior":
            if SENIOR_RE.search(title_lower):
                return True
    return False


def city_only(location: str) -> str:
    """Strip the country part from 'City, Country' for Glassdoor compatibility."""
    return location.split(",")[0].strip()


def filter_dataframe(df: pd.DataFrame, keyword: str) -> pd.DataFrame:
    """Apply title-relevance filtering to a scraped DataFrame."""
    if df.empty or "title" not in df.columns:
        return df

    before = len(df)
    filtered = df[df["title"].apply(lambda t: title_is_relevant(str(t), keyword))]
    removed = before - len(filtered)
    if removed > 0:
        import logging
        logging.getLogger(__name__).info(
            "Relevance filter: %d -> %d results (removed %d for '%s')",
            before, len(filtered), removed, keyword,
        )
    return filtered
