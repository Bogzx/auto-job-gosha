# GOSHA Platform Upgrade — Design Spec

**Date:** 2026-06-10
**Status:** Approved (user granted autonomous execution)
**Domain:** jobs.bogdantruta.com

## 1. Vision

Turn GOSHA from a Discord-only job bot into a **public web platform for Romanian CS students and early-career engineers**, with the website as the hub and Discord as the notification channel.

The killer feature is the **zero-setup personalized feed**: sign in with Discord, upload your CV (optional), and immediately see jobs ranked by CV-to-job semantic similarity — no filters or keywords required to get value in the first 30 seconds.

**UX is the top priority.** Everything must be really easy and good: mobile-friendly AND desktop-friendly, minimal clicks, instant value.

### Decisions made during brainstorming

| Question | Decision |
|---|---|
| Audience | Public tool for Romanian CS students |
| Bot vs web | Web is the hub; Discord notifies (slash commands kept working) |
| VPS | Medium (2–4 vCPU, 4–8 GB RAM), mostly empty; credentials provided later |
| Notifications | Join-server funnel: site prompts users to join the GOSHA Discord server for DM alerts |
| Scope | Build BOTH the web platform and the sources/extraction upgrade ("1 and 2 do everything") |
| Architecture | **Approach B: FastAPI JSON API + React SPA** (Vite + TypeScript + Tailwind) |
| Main screen layout | Hybrid: desktop = split view (filters \| list \| detail) with match % + "why this matches" explanations; mobile = single-column feed, filter bottom-sheet, full-screen detail |
| Apply tracking | **Clicking Apply auto-records an Application (status "applied") with an undo toast** — the Applied list builds itself |
| Workday scraping | Deferred to Phase 3; plugin architecture must make it a drop-in adapter (`*.myworkdayjobs.com/wday/cxs/...` JSON API) |
| Subscriptions on web | Full CRUD on the web with all filters; bot DMs work with zero slash-command setup |

## 2. Phases

- **Phase 1 — Web platform + deployment:** Postgres, API, SPA, Discord OAuth, feed (including job embedding generation at scrape time — the feed depends on it), browsing/filters, CV + cover letters, application tracker, subscription management, outbox→DM bridge, analytics, deploy to jobs.bogdantruta.com.
- **Phase 2 — Sources & extraction:** scraper plugin architecture, Romanian boards (eJobs, BestJobs, Hipo), RemoteOK, job-level cross-board dedup, posted-date/salary extraction, dead-link detection.
- **Phase 3 (deferred):** Workday adapter (configurable company list), email digests, more boards.

## 3. Architecture

### Processes (docker-compose on the VPS)

```
caddy (80/443, auto-TLS, serves SPA static build, proxies /api → api)
api   (uvicorn FastAPI — gosha.api)
bot   (existing Discord bot + APScheduler pipeline — unchanged role)
postgres (16 + pgvector, volume-backed)
```

- **Monorepo layout:** existing repo gains `web/` (React SPA) and `gosha/api/` (FastAPI app). The existing `gosha` package stays the shared domain layer (models, matching, filters, pipeline).
- **Web ↔ bot integration:** shared Postgres only. New `outbox` table: the web enqueues DM payloads (new-match alerts, test messages); the bot polls every ~30 s and sends. No gateway connection from the API process.
- **Auth:** Discord OAuth2 authorization-code flow in FastAPI. Session = signed, httpOnly, SameSite=Lax cookie (itsdangerous). Maps to existing `users.discord_user_id`. Admin = Discord ID allowlist (env), same as bot.
- **Database:** Postgres with pgvector. SQLAlchemy async (asyncpg) — already supported. **Alembic** replaces hand-rolled migrate.py for new migrations (migrate.py logic preserved for legacy SQLite upgrade path in the one-time migration script). One-time `scripts/migrate_sqlite_to_postgres.py` copies existing data.

### Frontend stack

Vite + React 18 + TypeScript + Tailwind CSS. TanStack Query for data fetching/caching. React Router. Recharts for admin charts. No SSR (accepted tradeoff of Approach B).

**Responsive strategy (mobile-first):**
- Mobile: bottom tab bar (Feed, Tracker, Searches, Profile), filter bottom-sheet, stacked list→detail navigation, touch targets ≥ 44 px.
- Desktop (≥ lg): top nav, split view — filter sidebar | job list | persistent detail pane.

## 4. Screens

1. **Landing (logged out):** value proposition, live job count, "Sign in with Discord". Fast, beautiful, one CTA.
2. **Onboarding (first login):** optional CV upload → instant feed. No CV → quick-pick chips (role + city) seed the feed. Skippable in one tap.
3. **Feed (home):** ranked jobs with match %, "why this matches you" line (top overlapping skills/terms), source badges, posted-age, salary when known. Actions per job: **Apply** (new tab + auto-track + undo toast), Cover letter, 👍 / 👎. Filters: query, locations, experience, remote, salary min, source, posted-within, sort by match/date.
4. **Tracker:** applications grouped by status — applied → phone_screen → interview → offer / rejected / withdrawn. Status changes via drag (desktop) or tap-menu (mobile), notes per application. Auto-populated by Apply clicks.
5. **Searches:** saved searches (subscriptions) with full filter editing, pause/resume, per-search "DM me on Discord" toggle, smart-keyword and location-alias suggestions. Banner prompting server join when the bot can't DM yet.
6. **CV & letters:** upload (PDF/DOCX/TXT/MD ≤ 5 MB), preview extracted text, delete; cover letter generation per job (Gemini), history list, copy button.
7. **Profile:** Discord identity, notification prefs, tier, delete account.
8. **Admin (allowlist only):** DAU/WAU/MAU, signups, applies, feedback counts, jobs by source, scrape-cycle health, recent events.

## 5. API (FastAPI, `/api/v1`)

- `GET /auth/discord/login` → redirect; `GET /auth/discord/callback`; `POST /auth/logout`; `GET /me`
- `GET /jobs` (filters + cursor pagination), `GET /jobs/{id}`
- `GET /feed` (personalized ranking)
- `POST /jobs/{id}/feedback` (interested | not_relevant)
- `POST /jobs/{id}/apply-click` → creates/returns Application, idempotent
- `GET/POST /applications`, `PATCH/DELETE /applications/{id}`
- `GET/POST /subscriptions`, `PATCH/DELETE /subscriptions/{id}`, `POST /subscriptions/{id}/pause|resume`
- `GET/PUT/DELETE /cv`
- `GET /cover-letters`, `POST /jobs/{id}/cover-letter`
- `POST /events/pageview` (analytics ping)
- `GET /admin/stats|usage|scrape-health` (admin guard)

Consistent JSON error envelope; 401 → SPA redirects to landing.

## 6. Data model changes

- `users`: + `username`, `avatar_url`, `created_at`, `last_login_at`, `in_guild` (bot can DM).
- `jobs`: + `embedding vector(768)` (pgvector), `posted_at`, `dedup_group_id`, `last_checked_at`.
- `applications`: + `source` ('web' | 'discord'); auto-created on apply click.
- `subscriptions`: + `name`, `notify_discord` (default true).
- **New `outbox`**: `id, user_id, kind, payload JSON, created_at, sent_at, attempts, last_error`.
- `events`: reused for analytics with new kinds (`web.pageview`, `web.signin`, `web.apply_click`, …).

## 7. Recommendation engine

- Embed jobs at scrape time (`all-mpnet-base-v2`, 768-dim) → pgvector column.
- User vector = CV embedding, refined by feedback: + mean of liked-job vectors, − mean of disliked (weighted; existing feedback profile logic informs term-level explanations).
- Feed = cosine top-50 (paginated) over active jobs first seen in the last 30 days, optional location pre-filter from the user's searches.
- "Why this matches": top overlapping informative terms between CV text and job description (simple TF-based overlap — cheap, explainable).
- No CV and no feedback → recency + popularity fallback, quick-pick chips build a temporary query embedding.

## 8. Sources & extraction (Phase 2 detail)

- `gosha/scrapers/` package: `BaseScraper` protocol — `async def search(query: SearchQuery) -> list[RawJob]`; registry; per-source rate limits; proxy support via existing tunnel manager.
- Adapters: `JobSpyScraper` (wraps current Indeed/LinkedIn/Glassdoor), `EjobsScraper`, `BestJobsScraper`, `HipoScraper`, `RemoteOKScraper`. Each lands with recorded-fixture tests.
- Salary normalization: Romanian boards quote monthly RON; normalize to a canonical (currency, period) and store both raw and normalized; convert for filtering.
- Posted-date extraction per source; description HTML→clean text; tech-tag extraction via curated keyword list.
- **Job-level cross-board dedup** (replaces delivery-time-only dedup): normalized (title, company) fuzzy match → `dedup_group_id`; UI shows one card with multiple source links.
- Dead-link detection: daily sampled HEAD/GET on active jobs > 7 days old; 404/410 → `is_active = false`.

## 9. Analytics

Homegrown, privacy-friendly (no third-party): API middleware + SPA pageview pings into `events`. Admin dashboard charts: DAU/WAU/MAU, signups, applies/day, feedback/day, jobs by source, scrape success rate. No cookies beyond the session.

## 10. Deployment

- `docker-compose.prod.yml` with the four services; Caddyfile with `jobs.bogdantruta.com` (auto-HTTPS).
- SPA built in CI or in Dockerfile multi-stage; Caddy serves `dist/` + proxies `/api`.
- `deploy.sh` on VPS: `git pull && docker compose -f docker-compose.prod.yml up -d --build`.
- GitHub Actions: lint + tests on push (deploy stays manual initially).
- **User-provided prerequisites (blockers only at deploy time):** VPS credentials, DNS A record for jobs.bogdantruta.com, Discord app OAuth2 redirect URI + client secret.
- Dev mode: SQLite still works for local dev (pgvector features degrade to numpy brute-force scoring), docker optional.

## 11. Error handling

- API: error envelope `{error: {code, message}}`; input validation via Pydantic; rate limiting on auth + expensive endpoints (slowapi).
- Outbox: retries with backoff, `attempts`/`last_error` recorded; dead after 5 attempts, visible in admin.
- Scrapers: one source failing never kills the cycle (per-adapter isolation, logged to events).
- Frontend: TanStack Query retries, toast on mutation failure, optimistic updates with rollback (feedback, apply-track, status changes).

## 12. Testing

- Backend: pytest — API routes via httpx AsyncClient with mocked Discord OAuth; unit tests for ranking, outbox, dedup, salary normalization; adapter tests on recorded fixtures. Existing bot test suite must keep passing.
- Frontend: Vitest + React Testing Library for core components (job card, filters, tracker board); Playwright smoke flow optional later.

## 13. Amendments (planning-time)

- **pgvector dropped (YAGNI):** embeddings stored as `LargeBinary` float32, scored with numpy brute force — identical behavior on SQLite dev and Postgres prod; revisit only past ~100k jobs.
- **Alembic dropped:** the existing hand-rolled idempotent `migrate.py` is extended (dialect-aware) instead; it already has test coverage and the migration surface is small.

## 14. Out of scope (explicitly)

- Payments/monetization (tier system stays config-only)
- Email delivery (join-server funnel chosen instead)
- Workday + additional boards (Phase 3)
- Native mobile apps (responsive web instead)
