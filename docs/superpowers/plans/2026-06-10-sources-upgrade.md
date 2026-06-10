# Sources & Extraction Upgrade (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Romanian job boards (eJobs, BestJobs, Hipo) and RemoteOK through a scraper plugin architecture, plus job-level cross-board dedup, salary/posted-date extraction, and dead-link detection.

**Architecture:** New `gosha/scrapers/` package: each source implements `BaseScraper.search(SearchQuery) -> list[RawJob]` with a pure `_parse()` testable on recorded fixtures. The pipeline's scrape stage fans out to all registered adapters after JobSpy; results funnel into the existing `upsert_jobs`. Dedup assigns `jobs.dedup_group_id` (canonical row points at itself); the API hides non-canonical rows.

**Tech Stack:** httpx (async), recorded JSON/HTML fixtures, regex HTML extraction for Hipo (no new heavy deps).

**Endpoint reality (probed live 2026-06-10):**
- RemoteOK: `GET https://remoteok.com/api` — JSON list, needs User-Agent; fields position/company/location/url/date/salary_min/salary_max/description.
- eJobs: `GET https://api.ejobs.ro/jobs?page&pageSize&q=<kw>` filters by keyword; `cityId` param ignored → client-side city filter via `GET /cities` (id→name map). Salary strings like "5000 - 10000 RON" (monthly). Detail at `/jobs/{id}` (not used v1). Job URL: `https://www.ejobs.ro/user/locuri-de-munca/{slug}/{id}`.
- BestJobs: `GET https://api.bestjobs.eu/v1/jobs?keyword=<kw>&location=<city-slug-romania>` — JSON `items`, ~100/page; salary strings monthly EUR; URL `https://www.bestjobs.eu/ro/loc-de-munca/{slug}`. No description in list payload (left empty v1).
- Hipo: HTML at `https://www.hipo.ro/locuri-de-munca/cautajob/IT-Software/{City}` — cards: `a.job-title[title][href]`, `p.company-name span`. IT-Software domain hardcoded (CS audience); keyword relevance handled by existing filters.

### Task P2-1: scrapers package core (base + salary + registry)
Files: `gosha/scrapers/{__init__,base,salary,registry}.py`, `tests/scrapers/test_base.py`
- RawJob dataclass (url,title,company,location,description,salary_min,salary_max,salary_currency,posted_at,source) + `to_record()` matching `upsert_jobs` column names (job_url/site/min_amount/max_amount/currency/date_posted).
- `parse_salary_range("5000 - 10000 RON", default_currency=None) -> (min,max,currency)`.
- Registry maps name → scraper instance; `get_extra_scrapers()` returns all four (always-on, additive to JobSpy boards).

### Task P2-2..P2-5: adapters (remoteok, ejobs, bestjobs, hipo)
Files: `gosha/scrapers/<name>.py`, `tests/scrapers/test_<name>.py`, `tests/scrapers/fixtures/<name>.*`
- Pure `_parse(payload, query) -> list[RawJob]` tested on fixtures recorded from the live probes.
- `search()` = httpx GET with UA + timeout + try/except → [] on failure (a dead source never kills the cycle).
- eJobs: module-level cached city map; match query location against city names client-side. BestJobs: location slug derived from `normalize_location` search string ("Cluj-Napoca, Romania" → "cluj-napoca-romania"). Hipo: regex card extraction; city slug from search string; only IT-Software domain. RemoteOK: single feed fetch cached per cycle; filter by keyword tokens + remote-ok semantics.

### Task P2-6: pipeline integration + posted_at extraction
Files: `gosha/pipeline.py`, `gosha/scraper.py` (no change), `tests/test_pipeline_sources.py`
- `upsert_jobs` reads `date_posted` → `Job.posted_at` (also benefits JobSpy rows which carry date_posted).
- `run_scrape_stage` fans out to extra scrapers per (keyword, location) combo, converts RawJobs → records → same upsert path.

### Task P2-7: cross-board dedup
Files: `gosha/models.py` (+`dedup_group_id`), `gosha/migrate.py`, `gosha/dedup.py`, `gosha/api/jobs.py` + `feed`/`recommend` filters, `tests/test_dedup.py`
- `normalize_key(title, company)`; `assign_dedup_groups()` over active jobs from last 30 days; canonical = lowest id; rows get `dedup_group_id = canonical_id`.
- API/browse/feed exclude rows where `dedup_group_id != NULL AND dedup_group_id != id`.
- Pipeline runs dedup after upsert; delivery-time dedup stays as a second net.

### Task P2-8: dead-link detection
Files: `gosha/deadlinks.py`, `gosha/main.py` (daily job), `tests/test_deadlinks.py`
- Sample ≤200 active jobs with `last_checked_at` null-or-oldest and `first_seen_at < now-7d`; HEAD (fallback GET) with 10s timeout; 404/410 → `is_active=False` + `job.expired` event; always stamp `last_checked_at` (new column).

### Task P2-9: UI + docs polish
Files: `web/src/components/FilterPanel.tsx` (+sources), `web/src/lib/format.ts` (labels exist), README.
- Final: full backend + frontend suites green.
