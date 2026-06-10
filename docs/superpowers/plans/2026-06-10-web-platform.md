# GOSHA Web Platform (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship jobs.bogdantruta.com — a React SPA + FastAPI platform where users sign in with Discord, get a CV-personalized job feed, manage searches, auto-track applications on Apply click, and receive Discord DMs with zero slash-command setup.

**Architecture:** The existing `gosha` package stays the shared domain layer. A new `gosha/api` FastAPI app serves `/api/v1` JSON; a new `web/` Vite+React+TS+Tailwind SPA consumes it. Bot and API share one database; web→Discord messages go through a new `outbox` table the bot polls. Postgres in prod, SQLite in dev — embeddings stored as `LargeBinary` float32 and scored with numpy (no pgvector; revisit only if job count exceeds ~100k).

**Tech Stack:** FastAPI, SQLAlchemy async (aiosqlite/asyncpg), itsdangerous sessions, httpx, sentence-transformers, React 18 + TypeScript + Vite + Tailwind CSS + TanStack Query + React Router + Recharts, Caddy, Docker Compose.

**Deviations from spec (deliberate):** numpy brute-force instead of pgvector; hand-rolled `migrate.py` extended instead of Alembic. Both noted in the spec amendments section.

---

## Shared contracts (referenced by all tasks)

### New/changed DB columns (Task 2 creates all of these)

```
users:          + username TEXT NULL, avatar_url TEXT NULL,
                + created_at TIMESTAMP NULL, last_login_at TIMESTAMP NULL,
                + in_guild BOOLEAN NOT NULL DEFAULT 0,
                + cv_embedding BLOB NULL          # float32 bytes, 768-dim
jobs:           + embedding BLOB NULL              # float32 bytes, 768-dim
                + posted_at TIMESTAMP NULL
subscriptions:  + name TEXT NULL, notify_discord BOOLEAN NOT NULL DEFAULT 1
applications:   + source TEXT NOT NULL DEFAULT 'discord'   # 'web' | 'discord'
outbox (new):   id PK, user_id FK users, kind TEXT, payload TEXT (JSON),
                created_at, sent_at NULL, attempts INT DEFAULT 0, last_error TEXT NULL
```

### API surface (`/api/v1`)

All responses JSON. Errors: `{"error": {"code": "<machine_code>", "message": "<human>"}}` with proper HTTP status. Auth = signed `gosha_session` cookie (itsdangerous `URLSafeTimedSerializer`, payload `{"uid": <users.id>}`, max_age 30 days, httpOnly, SameSite=Lax, Secure in prod).

```
GET  /auth/discord/login            → 307 to Discord authorize (scope: identify guilds.join), state in signed cookie
GET  /auth/discord/callback?code    → upsert user, set session, try guild-join, 307 to "/" (or "/welcome" if new)
POST /auth/logout                   → clears cookie → {"ok": true}
GET  /me                            → {"id", "discord_id" (str), "username", "avatar_url", "tier", "in_guild",
                                       "has_cv", "is_admin"} | 401

GET  /jobs?q&locations&experience&sources&salary_min&posted_within_days&remote&sort=match|date&page&per_page
                                    → {"items": [JobOut], "total": int, "page": int, "per_page": int}
GET  /jobs/{id}                     → JobOut (with full description)
POST /jobs/{id}/feedback            body {"feedback": "interested"|"not_relevant"} → {"ok": true}
POST /jobs/{id}/apply-click         → ApplicationOut (idempotent get-or-create, status=applied, source=web)

GET  /feed?page&per_page            → same shape as /jobs; items carry "match_score" 0..1 and "match_reasons": [str]

GET    /applications                → {"items": [ApplicationOut]}
POST   /applications                body {"job_id": int} → ApplicationOut
PATCH  /applications/{id}           body {"status"?: str, "notes"?: str} → ApplicationOut
DELETE /applications/{id}           → {"ok": true}

GET    /subscriptions               → {"items": [SubscriptionOut]}
POST   /subscriptions               body SubscriptionIn → SubscriptionOut  (enforces tier limits)
PATCH  /subscriptions/{id}          body partial SubscriptionIn → SubscriptionOut
DELETE /subscriptions/{id}          → {"ok": true}
POST   /subscriptions/{id}/pause    → SubscriptionOut
POST   /subscriptions/{id}/resume   → SubscriptionOut

GET    /cv                          → {"filename": str|null, "text": str|null, "uploaded_at": str|null}
PUT    /cv                          multipart file (pdf/docx/txt/md, ≤5MB) → CV response; re-embeds user vector
DELETE /cv                          → {"ok": true}

GET  /cover-letters                 → {"items": [{"id","job_id","job_title","company","content","created_at"}]}
POST /jobs/{id}/cover-letter        → {"content": str, "cached": bool}   (Gemini; quota by tier)

POST /events/pageview               body {"path": str} → {"ok": true}   (user optional)

GET  /admin/stats                   → counts (users, jobs, active jobs, subs, deliveries, feedback, applications)
GET  /admin/usage?days=30           → {"days": [{"date", "pageviews", "active_users", "signups", "applies"}]}
GET  /admin/scrape-health           → {"last_cycle_at", "jobs_by_source": {...}, "recent_events": [...]}
```

`JobOut`: `{"id", "url", "title", "company", "location", "description" (list view: first 240 chars), "salary_min", "salary_max", "salary_currency", "source", "posted_at", "first_seen_at", "match_score" (nullable), "match_reasons" (nullable list), "feedback" (nullable), "applied" (bool)}`

`ApplicationOut`: `{"id", "job_id", "status", "notes", "applied_at", "updated_at", "source", "job": {"id","title","company","location","url","source"}}`

`SubscriptionIn`: `{"name"?, "keywords": [str], "locations": [str], "excluded_keywords"?: [str], "company_blacklist"?: [str], "experience_levels"?: [str], "remote_ok"?: bool, "salary_min"?: int, "max_age_days"?: int, "notify_discord"?: bool}`

### Module interfaces

```python
# gosha/embeddings.py
def encode_texts(texts: list[str]) -> "np.ndarray | None"      # lazy model, None if unavailable
def vec_to_bytes(vec: "np.ndarray") -> bytes                     # float32 .tobytes()
def bytes_to_vec(raw: bytes) -> "np.ndarray"
async def embed_new_jobs(limit: int = 500) -> int                # jobs with embedding IS NULL → fill; returns count
async def embed_user_cv(user_id: int, cv_text: str) -> bool

# gosha/recommend.py
async def build_user_vector(user_id: int) -> "np.ndarray | None" # cv_embedding +0.3*mean(liked) -0.3*mean(disliked), L2-normalized
async def get_feed(user_id: int, page: int, per_page: int) -> tuple[list[tuple[Job, float, list[str]]], int]
def match_reasons(cv_text: str, job_description: str, top_k: int = 3) -> list[str]

# gosha/outbox.py
async def enqueue(user_id: int, kind: str, payload: dict) -> Outbox
async def process_outbox(bot) -> int   # called by scheduler every 30s; sends DMs; retries ≤5
```

### Env vars added

```
SESSION_SECRET=            # required for API
DISCORD_CLIENT_ID=         # OAuth app (same Discord application as the bot)
DISCORD_CLIENT_SECRET=
DISCORD_REDIRECT_URI=https://jobs.bogdantruta.com/api/v1/auth/discord/callback
DISCORD_GUILD_ID=          # server to auto-join users into
DISCORD_INVITE_URL=        # fallback invite link shown in UI
PUBLIC_BASE_URL=https://jobs.bogdantruta.com
```

### Conventions

- All new backend code: `from __future__ import annotations`, async SQLAlchemy via `gosha.database.get_session`, pure logic separated from IO (mirrors existing style).
- TDD: every task writes failing tests first, runs them, implements, re-runs, commits. Test command: `python -m pytest tests/<file> -v` (Windows dev box; CI runs Linux).
- Frontend tests: `cd web && npx vitest run`.
- Commit style: existing repo uses short imperative subjects ("Add X", "Use Y").

---

### Task 1: Dev infrastructure — Postgres option, new deps, config

**Files:**
- Modify: `requirements.txt` (add `asyncpg`, `itsdangerous` already present, `slowapi`)
- Modify: `gosha/config.py` (add web settings block)
- Create: `docker-compose.dev.yml` (postgres 16 service for local prod-parity testing)
- Modify: `gosha/env.example`, `.env.example` (new vars from Contracts)
- Test: `tests/test_config.py` (new)

- [ ] **Step 1: Write failing test** — `tests/test_config.py`:

```python
import os
from gosha.config import load_web_settings

def test_web_settings_defaults(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "123")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "abc")
    ws = load_web_settings()
    assert ws.session_secret == "test-secret"
    assert ws.discord_client_id == "123"
    assert ws.redirect_uri.endswith("/api/v1/auth/discord/callback")
    assert ws.cookie_secure is False  # default dev

def test_web_settings_prod(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "s")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "1")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "x")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://jobs.bogdantruta.com")
    ws = load_web_settings()
    assert ws.cookie_secure is True
```

- [ ] **Step 2: Run** `python -m pytest tests/test_config.py -v` — expect FAIL (ImportError).
- [ ] **Step 3: Implement** `load_web_settings()` in `gosha/config.py`: frozen dataclass `WebSettings(session_secret, discord_client_id, discord_client_secret, redirect_uri, guild_id, invite_url, public_base_url, cookie_secure)`. `redirect_uri` defaults to `{PUBLIC_BASE_URL or 'http://localhost:8000'}/api/v1/auth/discord/callback`; `cookie_secure = public_base_url.startswith("https")`. Raise RuntimeError when SESSION_SECRET/CLIENT_ID/SECRET missing.
- [ ] **Step 4: Run tests** — expect PASS. Also run full suite `python -m pytest -q` to confirm nothing broke.
- [ ] **Step 5:** Add `docker-compose.dev.yml` (postgres:16-alpine, port 5433, volume, `POSTGRES_DB=gosha`), update env examples, add deps to `requirements.txt`.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "Add web settings, asyncpg, dev postgres compose"`

### Task 2: Model extensions, Outbox model, migrations

**Files:**
- Modify: `gosha/models.py` (new columns per Contracts + `Outbox` model)
- Modify: `gosha/migrate.py` (idempotent column adds + `outbox` table create; dialect-aware: works on SQLite and Postgres)
- Test: `tests/test_models.py` (extend), `tests/test_migrate.py` (extend)

- [ ] **Step 1: Failing tests** — extend `tests/test_models.py`:

```python
async def test_user_new_columns(session):
    u = User(discord_user_id=42, username="gosha", avatar_url="http://a/b.png", in_guild=True)
    session.add(u); await session.commit()
    assert u.in_guild is True and u.cv_embedding is None

async def test_outbox_roundtrip(session):
    u = User(discord_user_id=43); session.add(u); await session.commit()
    o = Outbox(user_id=u.id, kind="test_dm", payload=json.dumps({"text": "hi"}))
    session.add(o); await session.commit()
    assert o.attempts == 0 and o.sent_at is None
```

  And in `tests/test_migrate.py`: create a legacy-schema SQLite DB missing the new columns, run `run_migrations`, assert columns exist (follow the existing test pattern in that file).
- [ ] **Step 2: Run** both test files — expect FAIL.
- [ ] **Step 3: Implement** model changes + `Outbox` (table per Contracts; `payload` Text JSON; helper `payload_dict` property). In `migrate.py` add the new columns to the existing column-add list and create `outbox` via metadata create_all (it already runs after migrations — verify order).
- [ ] **Step 4: Run** full suite — PASS.
- [ ] **Step 5: Commit** — `"Extend models for web platform; add outbox table"`

### Task 3: SQLite → Postgres one-time migration script

**Files:**
- Create: `scripts/migrate_sqlite_to_postgres.py`
- Test: `tests/test_sqlite_to_pg_script.py` (uses two SQLite DBs to test the copy logic — the script must take src/dst URLs so the test can use `sqlite+aiosqlite://` for both)

- [ ] **Step 1: Failing test:** seed a source DB (1 user, 1 sub, 2 jobs, 1 user_job, 1 application, 1 cover letter, 3 events), run `copy_all(src_url, dst_url)`, assert counts match in dst and `users.discord_user_id` preserved.
- [ ] **Step 2:** Run — FAIL. **Step 3:** Implement: reflect models in dependency order (users → jobs → subscriptions → user_jobs → applications → cover_letters → events → outbox), bulk insert preserving PKs; after copy on Postgres, reset sequences (`SELECT setval(pg_get_serial_sequence(...))`) guarded by dialect check. CLI: `python scripts/migrate_sqlite_to_postgres.py sqlite+aiosqlite:///data/jobs.db postgresql+asyncpg://...`.
- [ ] **Step 4:** Run — PASS. **Step 5: Commit** — `"Add SQLite to Postgres migration script"`

### Task 4: Embeddings module + scrape-time embedding

**Files:**
- Create: `gosha/embeddings.py` (interface per Contracts; reuses the `SemanticMatcher` model loading pattern from `gosha/matching.py` — share one lazy global model)
- Modify: `gosha/pipeline.py` (`run_scrape_cycle` calls `await embed_new_jobs()` after Stage 1), `gosha/main.py` (hourly backfill job `embed_new_jobs` so historic jobs get vectors)
- Test: `tests/test_embeddings.py`

- [ ] **Step 1: Failing tests** (inject a fake encoder so tests never load the real model):

```python
import numpy as np
from gosha import embeddings

def fake_encode(texts):
    return np.stack([np.full(768, float(len(t)), dtype=np.float32) for t in texts])

async def test_embed_new_jobs_fills_missing(session, monkeypatch):
    monkeypatch.setattr(embeddings, "encode_texts", fake_encode)
    # seed 2 jobs without embeddings...
    n = await embeddings.embed_new_jobs()
    assert n == 2
    # reload jobs, assert embedding bytes present and round-trips via bytes_to_vec

def test_vec_roundtrip():
    v = np.random.rand(768).astype(np.float32)
    assert np.allclose(embeddings.bytes_to_vec(embeddings.vec_to_bytes(v)), v)
```

- [ ] **Step 2:** Run — FAIL. **Step 3:** Implement (job text via existing `build_job_text`; batch of `limit` jobs where `embedding IS NULL AND is_active`; graceful no-op returning 0 when model unavailable). **Step 4:** Run — PASS.
- [ ] **Step 5:** Wire into pipeline + scheduler (after-scrape call; hourly backfill). Run full suite. **Step 6: Commit** — `"Add job/CV embeddings module, embed at scrape time"`

### Task 5: Recommendation engine

**Files:**
- Create: `gosha/recommend.py` (interface per Contracts)
- Test: `tests/test_recommend.py`

- [ ] **Step 1: Failing tests** (fake vectors, no model):

```python
async def test_feed_ranks_by_cosine(session, monkeypatch):
    # user with cv_embedding = unit vector e1; jobs A (embedding≈e1) and B (orthogonal e2), both active & recent
    items, total = await recommend.get_feed(user.id, page=1, per_page=10)
    assert [j.id for j, _, _ in items] == [job_a.id, job_b.id]  # B still included, ranked lower
    assert items[0][1] > 0.9

async def test_feed_feedback_refinement(session):
    # no cv_embedding; one liked user_job with embedding e2 → user vector ≈ e2 → e2-job ranks first

async def test_feed_fallback_recency(session):
    # no cv, no feedback → jobs returned newest-first, match_score is None... (use 0.0 sentinel? No — None)

def test_match_reasons_overlap():
    cv = "Experienced with Python, React and Docker deployments"
    jd = "We need Python and Docker skills, Kubernetes a plus"
    assert recommend.match_reasons(cv, jd) == ["python", "docker"] or set(...) >= {"python", "docker"}
```

- [ ] **Step 2:** Run — FAIL. **Step 3:** Implement: candidates = active jobs, `first_seen_at >= now-30d`, `embedding IS NOT NULL` (fallback path drops that condition); numpy cosine vs user vector; excluded: jobs the user gave `not_relevant` feedback on; stopword list (small curated EN+RO set) for `match_reasons` with TF ranking over job text intersected with CV tokens (len ≥ 3). Page slicing after sort; `total` = candidate count.
- [ ] **Step 4:** Run — PASS. **Step 5: Commit** — `"Add CV-based recommendation engine"`

### Task 6: API skeleton — app factory, sessions, errors

**Files:**
- Create: `gosha/api/__init__.py`, `gosha/api/app.py`, `gosha/api/deps.py`, `gosha/api/schemas.py`
- Test: `tests/api/__init__.py`, `tests/api/conftest.py`, `tests/api/test_app.py`

- [ ] **Step 1:** `tests/api/conftest.py` — app + client fixtures:

```python
import pytest, pytest_asyncio
from httpx import AsyncClient, ASGITransport
from gosha.api.app import create_app

@pytest_asyncio.fixture
async def client(tmp_db, monkeypatch):  # tmp_db = existing DB fixture pattern from tests/conftest.py
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "1")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "x")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

def make_session_cookie(user_id: int) -> dict[str, str]:
    from gosha.api.deps import serializer
    return {"gosha_session": serializer().dumps({"uid": user_id})}
```

  `tests/api/test_app.py`: `GET /api/v1/health` → `{"ok": true}`; `GET /api/v1/me` without cookie → 401 with error envelope `{"error": {"code": "unauthenticated", ...}}`; unknown route → 404 envelope.
- [ ] **Step 2:** Run — FAIL. **Step 3:** Implement `create_app()`: routers mounted under `/api/v1`, exception handlers producing the envelope, `deps.py` with `serializer()` (itsdangerous, secret from `load_web_settings()`), `current_user` dependency (reads cookie, loads User, 401 `unauthenticated`), `admin_user` dependency (403 `forbidden` unless `discord_user_id` in `ADMIN_DISCORD_IDS`), `set_session_cookie(response, user_id)` / `clear_session_cookie(response)` helpers honoring `cookie_secure`.
- [ ] **Step 4:** Run — PASS. **Step 5: Commit** — `"Add FastAPI app skeleton with cookie sessions"`

### Task 7: Discord OAuth

**Files:**
- Create: `gosha/api/auth.py`
- Test: `tests/api/test_auth.py` (mock Discord with `respx` — add `respx` to `requirements-dev.txt`)

- [ ] **Step 1: Failing tests:** login redirects to `discord.com/oauth2/authorize` with `client_id`, `scope=identify guilds.join`, signed `state`; callback (mocked token + `users/@me` returning id/username/avatar, mocked guild-join PUT 201) creates the user (`username`, `avatar_url`, `last_login_at` set, `in_guild=True`), sets cookie, 307s to `/welcome` for new users and `/` for existing; bad state → 400 envelope; `/me` returns profile incl. `is_admin`; logout clears cookie.
- [ ] **Step 2:** Run — FAIL. **Step 3:** Implement with httpx AsyncClient: token exchange `POST https://discord.com/api/oauth2/token`, profile `GET https://discord.com/api/users/@me`, best-effort guild join `PUT https://discord.com/api/guilds/{gid}/members/{uid}` with bot token + user access_token (404/403 → `in_guild=False`, never fails the login). Emit `web.signin` event. Avatar URL: `https://cdn.discordapp.com/avatars/{id}/{hash}.png`.
- [ ] **Step 4:** Run — PASS. **Step 5: Commit** — `"Add Discord OAuth login flow"`

### Task 8: Jobs API (list, detail, feedback, apply-click)

**Files:**
- Create: `gosha/api/jobs.py`
- Test: `tests/api/test_jobs_api.py`

- [ ] **Step 1: Failing tests:** filter combos (q matches title/company, locations uses `normalize_location` match lists, salary_min, posted_within_days, source, remote, sort=date), pagination totals; detail includes full description; `POST feedback` updates the user's `UserJob` (creates one if the user never got a DM for it) and emits `user.feedback` event; **apply-click**: first call creates Application(status=applied, source=web) + emits `web.apply_click`, second call returns the same application (idempotent, no duplicate); `JobOut.applied` true afterwards.
- [ ] **Step 2:** Run — FAIL. **Step 3:** Implement; reuse `gosha/filters.py` helpers for location matching (SQL pre-filter on simple fields + Python post-filter for location lists, same approach as pipeline). **Step 4:** PASS. **Step 5: Commit** — `"Add jobs API with auto-tracked apply clicks"`

### Task 9: Feed API

**Files:**
- Create: `gosha/api/feed.py`
- Test: `tests/api/test_feed.py`

- [ ] Steps: failing test (user with fake cv_embedding gets ranked items with `match_score`/`match_reasons`; user without CV gets recency fallback with `match_score: null`) → implement thin route over `recommend.get_feed` → PASS → commit `"Add personalized feed endpoint"`.

### Task 10: Applications API

**Files:**
- Create: `gosha/api/applications.py`
- Test: `tests/api/test_applications_api.py`

- [ ] Steps: failing tests (list returns embedded job summaries ordered by `updated_at` desc; POST creates; PATCH validates status against `APPLICATION_STATUSES` → 422 `invalid_status` otherwise, updates `updated_at`; DELETE removes — this is the Apply-undo path; cross-user access → 404) → implement → PASS → commit `"Add applications API"`.

### Task 11: Subscriptions API

**Files:**
- Create: `gosha/api/subscriptions.py`
- Test: `tests/api/test_subscriptions_api.py`

- [ ] Steps: failing tests (CRUD; tier limits enforced via `user.limits` → 403 `tier_limit` with message; keyword/location count caps; pause/resume toggle `is_active`; `notify_discord` round-trips; creating first subscription enqueues outbox `welcome` DM when `in_guild`) → implement (reuse validation helpers from bot where extractable) → PASS → commit `"Add subscriptions API with tier limits"`.

### Task 12: CV + cover letters API

**Files:**
- Create: `gosha/api/cv.py`, `gosha/api/cover_letters.py`
- Test: `tests/api/test_cv_api.py`

- [ ] Steps: failing tests (PUT /cv with a small txt file stores text via existing `gosha/cover_letter.py` extraction helpers, sets `users.cv_embedding` (fake encoder), GET returns text, DELETE clears file + embedding; oversize → 413 `file_too_large`; bad ext → 422; POST cover-letter with mocked Gemini returns content and caches — second call `cached: true`; quota exceeded → 403 `quota_exceeded`) → implement, refactoring `cover_letter.py` storage helpers for reuse (keep bot commands working — run existing tests) → PASS → commit `"Add CV and cover letter API"`.

### Task 13: Outbox + bot bridge

**Files:**
- Create: `gosha/outbox.py`
- Modify: `gosha/main.py` (scheduler job every 30s), `gosha/bot.py` (only if DM helper needs exposing — reuse `_dm_user` from pipeline), `gosha/pipeline.py` (respect `subscription.notify_discord` in delivery; skip DM when False)
- Test: `tests/test_outbox.py`

- [ ] **Step 1: Failing tests:** `enqueue` writes a row; `process_outbox(fake_bot)` sends pending (fake bot records DMs), stamps `sent_at`; DM failure increments `attempts`, sets `last_error`, retries next call; after 5 attempts row is skipped (dead); kinds rendered: `welcome` ("Your searches are set up — I'll DM you new matches"), `test_dm`, `generic` (payload.text). Pipeline test: subscription with `notify_discord=False` → no DM sent for its matches.
- [ ] **Step 2:** Run — FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5: Commit** — `"Add outbox DM bridge between web and bot"`

### Task 14: Analytics + admin API

**Files:**
- Create: `gosha/api/analytics.py`, `gosha/api/admin.py`
- Modify: `gosha/events.py` (add kinds: `web.pageview`, `web.signin`, `web.apply_click` — just constants/emit helpers)
- Test: `tests/api/test_analytics_admin.py`

- [ ] Steps: failing tests (pageview stores event with nullable user; `/admin/*` 403 for non-admin, correct aggregates for seeded events — daily buckets, distinct-user active counts; scrape-health reads latest `job.discovered`/cycle events and per-source job counts) → implement (SQL `group by date()`, dialect-portable via `func.date`) → PASS → commit `"Add analytics tracking and admin API"`.

### Task 15: SPA scaffold + auth + landing

**Files:**
- Create: `web/` — Vite React-TS app: `package.json`, `vite.config.ts` (dev proxy `/api` → `http://localhost:8000`), `tailwind.config.js`, `postcss.config.js`, `index.html`, `src/main.tsx`, `src/App.tsx` (router), `src/api/client.ts` (fetch wrapper: JSON, credentials include, error envelope → typed `ApiError`, 401 → redirect to `/`), `src/api/types.ts` (mirror Contracts), `src/hooks/useMe.ts`, `src/components/Layout.tsx` (desktop top-nav / mobile bottom-tab shell), `src/pages/Landing.tsx`
- Modify: `.gitignore` (`web/node_modules`, `web/dist`)
- Test: `web/src/api/client.test.ts` (vitest: error envelope parsing), plus `npx tsc --noEmit` clean

- [ ] **Step 1:** Scaffold (`npm create vite@latest web -- --template react-ts`), add Tailwind v3, TanStack Query, React Router, vitest. **Step 2:** Failing client test → implement client. **Step 3:** Layout shell with the two responsive navigation patterns (no page content yet) + Landing with "Sign in with Discord" → `/api/v1/auth/discord/login`. **USE the frontend-design skill for Landing + Layout visual design** — distinctive, not generic. **Step 4:** `npx vitest run` + `npx tsc --noEmit` PASS; manual: `npm run dev` against `uvicorn gosha.api.app:create_app --factory`. **Step 5: Commit** — `"Scaffold React SPA with auth shell and landing page"`

### Task 16: Feed UI (the core screen)

**Files:**
- Create: `web/src/pages/Feed.tsx`, `src/components/JobCard.tsx`, `JobDetail.tsx`, `FilterPanel.tsx` (sidebar ≥lg / bottom-sheet below), `MatchBadge.tsx`, `src/components/Toast.tsx` (undo support), `src/hooks/useJobs.ts`, `useFeed.ts`
- Test: `web/src/components/JobCard.test.tsx`, `web/src/pages/Feed.test.tsx` (RTL with mocked fetch)

- [ ] **Step 1: Failing tests:** JobCard renders title/company/match badge/"why" reasons/source badge/posted-age; Apply click calls `POST /jobs/:id/apply-click` AND shows undo toast; undo calls `DELETE /applications/:id`; feedback buttons optimistic-toggle. Feed page: desktop split view renders list + detail panes; filter changes refetch with correct query params.
- [ ] **Step 2-3:** Implement per locked design: desktop = filters | list | persistent detail; mobile = single column → full-screen detail route, filter bottom-sheet, infinite scroll (TanStack `useInfiniteQuery`). Tabs: "For you" (feed) / "All jobs" (browse). **USE frontend-design skill.**
- [ ] **Step 4:** vitest + tsc PASS. **Step 5: Commit** — `"Add feed and job browsing UI"`

### Task 17: Tracker UI

**Files:**
- Create: `web/src/pages/Tracker.tsx`, `src/components/ApplicationCard.tsx`, `StatusSelect.tsx`, `src/hooks/useApplications.ts`
- Test: `web/src/pages/Tracker.test.tsx`

- [ ] Steps: failing tests (groups by status with counts; status change PATCHes and moves card; notes editable; empty state links to Feed) → implement (desktop: status columns; mobile: segmented list — no drag library, tap-to-change menu everywhere; YAGNI) → PASS → commit `"Add application tracker UI"`.

### Task 18: Searches UI

**Files:**
- Create: `web/src/pages/Searches.tsx`, `src/components/SearchForm.tsx`, `ChipInput.tsx` (keywords/locations chips with suggestions from a static copy of smart keywords + location aliases exposed via `GET /api/v1/meta` — add tiny endpoint in `gosha/api/app.py` returning `SMART_KEYWORDS` keys + `LOCATION_ALIASES` keys), `JoinServerBanner.tsx`
- Test: `web/src/pages/Searches.test.tsx`, extend `tests/api/test_app.py` for `/meta`

- [ ] Steps: failing tests (list shows searches with pause/resume; form validates ≥1 keyword + ≥1 location; tier-limit error surfaces as friendly message; `notify_discord` toggle; banner shows when `me.in_guild === false` with invite link) → implement → PASS → commit `"Add saved searches management UI"`.

### Task 19: CV page, Profile, Onboarding flow

**Files:**
- Create: `web/src/pages/CvPage.tsx` (upload dropzone, extracted-text preview, cover letters list with copy), `Profile.tsx`, `Welcome.tsx` (onboarding: 2 steps — upload CV (skippable) → quick-pick chips create first search → straight to Feed)
- Test: `web/src/pages/Welcome.test.tsx` (skip path lands on feed; upload path PUTs file)

- [ ] Steps: failing tests → implement (Welcome route is the post-OAuth redirect for new users; the whole flow ≤ 30 seconds, skippable at every step) → PASS → commit `"Add CV management, profile, and onboarding"`.

### Task 20: Admin UI

**Files:**
- Create: `web/src/pages/Admin.tsx` (Recharts: DAU/WAU line, signups + applies bars; stat cards; scrape-health table; visible only when `me.is_admin`)
- Test: `web/src/pages/Admin.test.tsx` (hidden for non-admin)

- [ ] Steps: failing test → implement → PASS → commit `"Add admin analytics dashboard"`.

### Task 21: Production build + deployment artifacts

**Files:**
- Create: `Caddyfile` (jobs.bogdantruta.com → serve `/srv/dist` SPA with `try_files` fallback to index.html; `handle /api/* → reverse_proxy api:8000`), `docker-compose.prod.yml` (caddy, api, bot, postgres + volumes; api/bot share image; SPA built via multi-stage `Dockerfile.web` whose dist lands in a shared volume OR built into the caddy image — use multi-stage caddy image: node build stage → copy dist into caddy image), `Dockerfile.api` reusing existing Dockerfile base with `CMD uvicorn gosha.api.app:create_app --factory --host 0.0.0.0 --port 8000`, `deploy.sh` (git pull; docker compose -f docker-compose.prod.yml up -d --build), `.github/workflows/ci.yml` (python tests + web tsc/vitest/build on push)
- Modify: `README.md` (deployment section: DNS A record, Discord portal redirect URI, .env on VPS, first-run SQLite→PG migration)
- Test: CI green; `docker compose -f docker-compose.prod.yml config` validates

- [ ] Steps: write artifacts → validate compose config + local prod-mode smoke (`docker compose -f docker-compose.prod.yml up` with a localhost Caddyfile variant — document `CADDY_SITE=:8080` env override for local testing) → commit `"Add production deployment stack"`.

### Task 22: Integration verification pass

- [ ] Run the FULL backend suite `python -m pytest -q` and web `npx vitest run`, `npx tsc --noEmit`, `npm run build` — all green.
- [ ] Manual E2E with playwright-cli against local stack (uvicorn + vite dev): landing renders, mock-login session (set cookie via test helper endpoint enabled only when `DEBUG_LOGIN=1` env — add `GET /api/v1/auth/debug-login?uid=` guarded by env flag, returns session cookie, for local testing without real Discord app), feed renders with seeded jobs, apply-click lands in tracker, search CRUD works, mobile viewport (390px) bottom tabs + filter sheet work.
- [ ] Fix anything found; commit fixes individually.
- [ ] Final commit + update spec amendments section with any further deviations.

---

## Self-review (done at planning time)

- **Spec coverage:** Postgres(T1/T3), models(T2), embeddings+feed(T4/T5/T9), OAuth+sessions(T6/T7), jobs+apply-click(T8), tracker(T10/T17), subscriptions+tier limits+DM toggle(T11/T18), CV+letters(T12/T19), outbox+notify_discord(T13), analytics+admin(T14/T20), responsive SPA(T15-T20), deploy+Caddy+CI(T21), error envelope+rate limiting(T6; slowapi on auth/cover-letter in T7/T12), onboarding(T19), join-server funnel(T7 guilds.join + T18 banner). Gap check: "events middleware" from spec folded into explicit pageview endpoint — accepted simplification.
- **Placeholders:** none found that hide unknown work; UI tasks intentionally delegate pixel design to the frontend-design skill with contracts pinned here.
- **Type consistency:** `JobOut.applied`/`match_score`/`match_reasons` used consistently in T8/T9/T16; `create_app` factory name consistent T6/T21/T22.
