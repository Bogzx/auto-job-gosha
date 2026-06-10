# GOSHA — Discord Job Hunter Bot

GOSHA (a.k.a. **JobHunter**) is a self-hosted Discord bot that continuously scrapes **Indeed**, **LinkedIn**, and **Glassdoor**, matches fresh postings against each user's subscriptions using semantic AI, and delivers them to Discord DMs with interactive feedback buttons and AI-generated cover letters.

It is built for CS students and early-career engineers who are tired of refreshing job boards, but any keyword/location search works.

---

## Table of Contents

1. [Feature Overview](#feature-overview)
2. [How It Works](#how-it-works)
3. [User Guide — Discord Commands](#user-guide--discord-commands)
4. [Smart Keywords & Locations](#smart-keywords--locations)
5. [Free vs Pro vs Unlimited](#free-vs-pro-vs-unlimited)
6. [Self-Hosting Quick Start](#self-hosting-quick-start)
7. [Configuration Reference](#configuration-reference)
8. [Architecture Deep Dive](#architecture-deep-dive)
9. [Data Model](#data-model)
10. [Admin Dashboard](#admin-dashboard)
11. [Semantic Matching](#semantic-matching)
12. [Cover Letter Generation](#cover-letter-generation)
13. [SSH Tunnel Proxy Rotation](#ssh-tunnel-proxy-rotation)
14. [Database Migrations](#database-migrations)
15. [Development](#development)
16. [Troubleshooting](#troubleshooting)
17. [Project Layout](#project-layout)

---

## Feature Overview

| Feature | Description |
|---|---|
| **Multi-board scraping** | Indeed, LinkedIn, Glassdoor via [JobSpy](https://github.com/Bunsly/JobSpy) |
| **Smart keyword expansion** | `"computer science internship"` auto-expands to 19 related job titles |
| **Location aliases** | Cluj, Bucharest, Berlin, "Romania", "Europe", "Remote", etc. |
| **Semantic matching** | `all-mpnet-base-v2` sentence embeddings + cosine similarity |
| **Feedback learning** | 👍/👎 buttons build a personal preference profile that adjusts future scores |
| **AI cover letters** | Gemini reads your CV + a job posting and writes a tailored cover letter |
| **Application tracker** | `/apply`, `/update_application` — a lightweight Kanban in Discord |
| **SSH SOCKS5 proxy rotation** | Route scraping through remote VPSs to dodge IP bans |
| **Cross-board dedup** | Same job on Indeed + LinkedIn + Glassdoor → one notification |
| **Web admin dashboard** | FastAPI on localhost:8080, reached via SSH tunnel |
| **Pause / Resume** | Freeze subscriptions during exams or after you get an offer |
| **Tier system** | Free / Pro / Unlimited with configurable quotas per tier |
| **Idempotent migrations** | Hand-rolled migration runner; safe to restart anytime |
| **Event audit trail** | Every scrape, match, delivery, feedback is logged to an `events` table |

---

## How It Works

```
           ┌──────────────────────────────────────────────────────┐
           │                Discord users via DMs                 │
           └────────────┬─────────────────────────▲───────────────┘
                        │ /subscribe, /quickstart  │ job embed + buttons
                        ▼                          │
        ┌──────────────────────────────┐           │
        │  Discord bot (discord.py)    │───────────┘
        └──────────────┬───────────────┘
                       │
          APScheduler  │ every N minutes
                       ▼
        ┌──────────────────────────────┐     ┌─────────────────────┐
        │  Stage 1: SCRAPE             │────▶│ JobSpy → Indeed /   │
        │  (gosha/pipeline.py)         │     │ LinkedIn / Glassdoor │
        └──────────────┬───────────────┘     └─────────────────────┘
                       │   upsert new jobs            via SOCKS5
                       ▼                              SSH tunnels
        ┌──────────────────────────────┐
        │  Stage 2: MATCH              │
        │  hard filters → semantic →   │
        │  feedback adjustment         │
        └──────────────┬───────────────┘
                       │   enqueue UserJob rows
                       ▼
        ┌──────────────────────────────┐
        │  Stage 3: DELIVER            │────▶ DM rich embeds to users
        │  dedup → send → mark         │
        └──────────────────────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │  SQLite (WAL mode)           │◀───  FastAPI admin dashboard
        │  jobs.db                     │      (localhost:8080)
        └──────────────────────────────┘
```

Each scrape cycle:

1. **Scrape** — Collect all active subscriptions, group by `(keyword, location, boards, max_age_days)`, fan out to JobSpy via randomly-selected SOCKS5 proxies. Deduplicate and upsert into the `jobs` table. Fires `job.discovered` / `job.updated` events.
2. **Match** — For every active subscription, filter candidate jobs against:
   - Excluded keywords
   - Company blacklist
   - Salary minimum
   - Experience level (intern/junior/mid/senior)
   - Location (substring match against the subscription's locations; `remote_ok` toggle includes remote matches)
   
   Then score remaining jobs with semantic similarity (if enabled), boost/penalize based on the user's past feedback, and enqueue a `user_jobs` row for each match.
3. **Deliver** — Read all pending `user_jobs`, cross-board dedup (same title+company from multiple sources → one DM), send a rich embed with buttons, mark as delivered.

---

## User Guide — Discord Commands

### Quick start

```
/quickstart location: cluj
```

Creates a single subscription searching 19 CS intern/junior job titles in your chosen city. Default `max_age_days: 14`, experience levels `intern + junior`, remote excluded.

### Subscriptions

| Command | Purpose |
|---|---|
| `/subscribe keyword:… location:… [experience] [max_age_days] [exclude] [salary_min]` | Create a custom search |
| `/my_searches` | Show all your active & paused subscriptions |
| `/edit id:… [keyword] [location] [max_age_days] [experience] [exclude] [blacklist] [salary_min]` | Modify fields of a subscription |
| `/pause id:…` | Temporarily stop a subscription without deleting it |
| `/resume id:…` | Re-enable a paused subscription |
| `/unsubscribe id:…` | Delete a subscription |
| `/show_keywords keyword:…` | Preview which titles a smart keyword expands to |

### Job discovery

| Command | Purpose |
|---|---|
| `/scrape_now` | Force an immediate scrape cycle (cooldown per tier) |
| `/stats` | Your delivery + feedback counts and active subscriptions |
| `/status` | Bot health — uptime, tunnel state, last scrape time *(admin only)* |

### Application tracking

| Command | Purpose |
|---|---|
| `/apply job_id:…` | Mark a job as applied |
| `/update_application job_id:… status:…` | Move through pipeline: applied → phone_screen → interview → offer → rejected / withdrawn |
| `/applications` | List your tracked applications grouped by status |

### AI cover letters

| Command | Purpose |
|---|---|
| `/upload_cv` | Attach a PDF/DOCX/TXT/MD CV (≤5 MB) |
| `/cover_letter job_id:…` | Generate a tailored cover letter (cached 30 days) |
| `/my_cv` | Preview stored CV + remaining monthly cover-letter quota |
| `/delete_cv` | Remove your stored CV |

### Interactive buttons on every job DM

- **Apply** — link to the posting
- **Cover Letter** — generate or fetch cached AI cover letter
- **Interested** 👍 — trains your preference profile upward
- **Not Relevant** 👎 — trains it downward (after 3+ ratings the bot starts applying the profile)

---

## Smart Keywords & Locations

### Smart keyword expansion

Some keywords automatically fan out into many specific search terms:

| Keyword | Expands to |
|---|---|
| `computer science internship` | 19 intern/junior titles — software engineer intern, data analyst intern, devops intern, QA intern, frontend/backend intern, etc. |
| `computer science` | 18 general tech titles (all levels) |
| `cs entry level` | 11 junior / graduate / trainee titles |
| `software engineering` | 9 developer roles (frontend, backend, full stack, mobile, platform…) |
| `data science` | 8 data / ML / AI roles |
| `tech internship` | 9 tech + product + UX intern roles |

Anything not in the list is searched verbatim. Use `/show_keywords keyword:…` to inspect the expansion.

### Location aliases

- **Romania:** `cluj`, `bucharest` / `bucuresti`, `timisoara`, `iasi`, `brasov`, `sibiu`, `craiova`, `constanta`, `oradea`, or `romania` (all cities).
- **Europe:** `dublin`, `london`, `berlin`, `amsterdam`, `prague`, `warsaw`, `budapest`, `krakow`, `vienna`, `munich`, `paris`, `barcelona`, `zurich`. Use `europe` or `eu` for the whole continent.
- **Remote:** `remote` matches remote / work-from-home / anywhere.
- **Custom:** anything else is searched verbatim on the job boards.

Aliases live in `gosha/filters.py` (`LOCATION_ALIASES`). Each alias has a `search` string (sent to job boards) and a `match` list (substrings used to filter scraped results).

**Important note about `remote_ok`:** when you create a subscription, `remote_ok` is **off by default**. You will only get jobs matching your listed locations. If you want remote jobs too, use `/edit` to flip it on (or subscribe with `location: remote`).

---

## Free vs Pro vs Unlimited

Limits live in `TIER_LIMITS` in `gosha/models.py` — edit them there to tune. Defaults:

| Limit | Free | Pro | Unlimited |
|---|---|---|---|
| Subscriptions | 5 | 15 | 999 |
| Keywords per subscription | 5 | 10 | 50 |
| Locations per subscription | 3 | 10 | 50 |
| Tracked applications | 10 | 999 | 999 |
| Cover letters per month | 5 | 999 | 999 |
| `/scrape_now` cooldown | 300 s | 120 s | 60 s |
| Semantic matching | Yes | Yes | Yes |
| Priority delivery | No | Yes | Yes |
| Email delivery | No | Yes | Yes |
| Webhook delivery | No | No | Yes |

Upgrading a user is a direct DB write on the `users.tier` column — no payment flow is built in.

---

## Self-Hosting Quick Start

Prerequisites: Docker + Docker Compose, a Discord bot token, (optionally) a Gemini API key and one or more VPSs for SSH tunnels.

```bash
git clone <this-repo>
cd autojobGOSHA

# Prepare env file
cp gosha/env.example .env
# Edit .env — at minimum set DISCORD_TOKEN
nano .env

# (optional) drop SSH keys in ./keys for proxy tunnels
mkdir -p keys
cp ~/.ssh/vps_key keys/id_rsa
chmod 600 keys/id_rsa

# Build and start
docker compose up -d --build

# Watch logs
docker compose logs -f job-bot
```

On first run the bot will:

1. Create `data/jobs.db` (SQLite in WAL mode).
2. Run idempotent migrations to add any missing columns.
3. Spawn SSH tunnels to each configured VPS on ports `1080`, `1081`, `1082`…
4. Connect to Discord and sync slash commands globally.
5. Schedule the scrape cycle (`SCRAPE_INTERVAL_MINUTES`, default 60).

The admin dashboard is bound to `127.0.0.1:8080` — forward it through SSH to your laptop:

```bash
ssh -L 8080:127.0.0.1:8080 user@your-server
# then open http://localhost:8080/admin/ in a browser
```

### Invite the bot to your Discord server

Scopes: `bot`, `applications.commands`. Minimum permissions: `Send Messages`, `Embed Links`, `Use Application Commands`, `Read Message History`. Users must have **DMs from server members** enabled to receive job embeds.

---

## Deploying the Web Platform (jobs.bogdantruta.com)

The repo now ships a full public web platform: React SPA + FastAPI API +
Postgres + Caddy (auto-HTTPS), alongside the original Discord bot.

**One-time setup on the VPS:**

1. **DNS** — add an `A` record: `jobs.bogdantruta.com` → VPS IP.
2. **Discord application** (same app as the bot, Developer Portal → OAuth2):
   - copy the **Client ID** and **Client Secret** into `.env`
   - add redirect URI: `https://jobs.bogdantruta.com/api/v1/auth/discord/callback`
3. **Env** — `cp .env.example .env` and fill in at minimum: `DISCORD_TOKEN`,
   `SESSION_SECRET`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`,
   `PUBLIC_BASE_URL=https://jobs.bogdantruta.com`, `POSTGRES_PASSWORD`,
   `DISCORD_GUILD_ID` + `DISCORD_INVITE_URL` (join-server funnel), and a
   cover-letter LLM key (`GEMINI_API_KEY` or `OPENROUTER_API_KEY`).
4. **Launch:** `docker compose -f docker-compose.prod.yml up -d --build`
5. **Migrate old SQLite data** (only if upgrading an existing bot install):

   ```bash
   docker compose -f docker-compose.prod.yml run --rm bot \
     python scripts/migrate_sqlite_to_postgres.py \
     sqlite+aiosqlite:///data/jobs.db \
     "postgresql+asyncpg://gosha:$POSTGRES_PASSWORD@postgres:5432/gosha"
   ```

Updates afterwards: `./deploy.sh` (git pull + rebuild + restart).

Local prod-parity test without the domain: set `CADDY_SITE=:8080` in `.env`,
then browse `http://localhost:8080`.

### AI provider for cover letters

Generation auto-detects the provider: **OpenRouter** when
`OPENROUTER_API_KEY` is set (model from `OPENROUTER_MODEL`, e.g. a DeepSeek
variant), otherwise **Gemini**. Force one with `LLM_PROVIDER=openrouter|gemini`.

---

## Configuration Reference

All settings are read from environment variables (loaded via `gosha/config.py`). See `gosha/env.example` for the full template.

### Required

| Variable | Purpose |
|---|---|
| `DISCORD_TOKEN` | Bot token from the Discord developer portal |

### Database

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/jobs.db` | SQLAlchemy async URL. PostgreSQL works too (`postgresql+asyncpg://…`) |

### Scraping

| Variable | Default | Purpose |
|---|---|---|
| `SCRAPE_INTERVAL_MINUTES` | `60` | How often the scheduler runs the scrape cycle |
| `ALERT_CHANNEL_ID` | `0` | Discord channel ID for optional scrape summaries (0 = off) |

### Semantic matching

| Variable | Default | Purpose |
|---|---|---|
| `USE_SEMANTIC_MATCHING` | `false` | Toggle embedding-based scoring. When off, falls back to regex title matching |
| `SEMANTIC_MODEL` | `all-mpnet-base-v2` | Any `sentence-transformers` model name |
| `SEMANTIC_THRESHOLD` | `0.40` | Cosine similarity cutoff (0–1). Lower → more matches, less relevant |

### Admin

| Variable | Purpose |
|---|---|
| `ADMIN_DISCORD_IDS` | Comma-separated Discord user IDs who can run admin-only commands (`/scrape_now`, `/status`) |

### Gemini (cover letters)

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | API key from Google AI Studio. Without this, cover letter commands return a friendly error |

### SSH tunnels (SOCKS5 proxy rotation)

Up to 9 VPSs, numbered `1`–`9`:

| Variable | Purpose |
|---|---|
| `VPS_1_HOST` | Hostname or IP |
| `VPS_1_USER` | SSH username |
| `VPS_1_PORT` | SSH port (1024–65535) |
| `VPS_1_KEY` | Path to private key inside the container |
| `SSH_KEY_PATH` | Fallback key path if `VPS_N_KEY` is unset. Default `/home/app/.ssh/id_rsa` |

The bot opens a SOCKS5 dynamic tunnel per VPS on local ports `1080 + index`. Each scrape picks a random active tunnel; a watchdog restarts dead ones every 5 minutes.

If no VPSs are configured, the bot runs everything directly. That's fine for low volume, but you will eventually get rate-limited or IP-banned by LinkedIn/Glassdoor.

---

## Architecture Deep Dive

### Entry point

`main.py` is a shim that delegates to `gosha.main.main()`. `gosha/main.py` performs the startup sequence:

1. Load settings (`gosha.config.load_settings`).
2. Initialize the DB (`gosha.database.init_db` → runs `gosha.migrate.run_migrations`, then `Base.metadata.create_all`).
3. Create an `SSHTunnelManager` and start all configured tunnels.
4. Instantiate the `JobBot` (subclass of `discord.ext.commands.Bot`).
5. Create an `AsyncIOScheduler` and register two jobs:
   - `scrape_cycle` — every `scrape_interval_minutes`, runs the full 3-stage pipeline.
   - `tunnel_health_check` — every 5 minutes, restarts dead SSH tunnels.
6. Start the Discord client. The scheduler starts in `on_ready`.
7. Install SIGINT/SIGTERM handlers for graceful shutdown (close scheduler → stop tunnels → close bot).

### The three pipeline stages

`gosha/pipeline.py`:

- **`run_scrape_stage()`** — groups subscriptions by scrape key to avoid duplicate work, calls `gosha.scraper.scrape_jobs_raw()` per group, deduplicates, and bulk-upserts into `jobs`.
- **`run_match_stage()`** — loads every active subscription, pre-filters with `job_matches_subscription()` (hard filters), then either semantic-scores via `SemanticMatcher` or regex-matches titles. Feedback profiles from `gosha/feedback.py` adjust the score per user. New matches become `user_jobs` rows with `delivered_at = NULL`.
- **`_deliver_new()`** — reads pending `user_jobs`, cross-board dedups by `(title, company, user_id)`, builds the embed (`gosha.delivery.build_job_embed`), sends it, stamps `delivered_at`.

### Scraper

`gosha/scraper.py` wraps JobSpy's `scrape_jobs()`. Each call picks a proxy from the tunnel manager's active list, builds the search URL, and filters out invalid rows. If no tunnels are available it runs directly.

Keyword expansion and location aliasing both live in `gosha/filters.py` and are applied here before hitting JobSpy, so the scraper never sees the user-facing shorthand.

### Discord bot

`gosha/bot.py` defines a single cog (`GoshaCog`) with ~20 slash commands. Notable pieces:

- **Autocomplete** — `/subscribe`'s keyword and location fields offer suggestions from the smart-keyword list and `LOCATION_ALIASES`.
- **Persistent buttons** — `gosha/views.py` defines `JobFeedbackView` with custom IDs encoded as `feedback:{user_id}:{job_id}:{action}`, so buttons keep working across bot restarts.
- **Tier enforcement** — each command that creates resources checks `user.limits` (derived from the tier).
- **Cooldowns** — `/scrape_now` enforces a per-user cooldown from the tier config.

### Feedback and preference profiles

`gosha/feedback.py` builds a `UserPreferenceProfile` from the user's `user_jobs.feedback` history (`interested` / `not_relevant`). The profile extracts recurring terms and companies from liked and disliked postings, then applies a ±0.3 adjustment to future semantic scores where those terms show up. After 3+ pieces of feedback the profile is considered reliable and starts contributing.

### Events

`gosha/events.py` is a lightweight audit trail. Every significant action (`job.discovered`, `job.matched`, `job.delivered`, `user.feedback`, `subscription.created`, …) is inserted into the `events` table with a timestamp, optional actor/job/subscription IDs, and a JSON payload. There is no external queue — the `events` table is the queue.

---

## Data Model

All models live in `gosha/models.py`. SQLite in WAL mode, but the schema works on PostgreSQL too.

| Table | Purpose |
|---|---|
| `users` | Discord user IDs with a `tier` column (`free` / `pro` / `unlimited`) |
| `subscriptions` | A user's search: JSON-list columns for `keywords`, `locations`, `excluded_keywords`, `company_blacklist`, `experience_levels`, `boards`; scalars for `remote_ok`, `salary_min`, `max_age_days`, `is_active` |
| `jobs` | Canonical job record keyed by URL. Tracks `first_seen_at` / `last_seen_at` / `is_active` for freshness |
| `user_jobs` | The match + delivery queue. `(user_id, job_id)` unique. Holds `relevance_score`, `delivered_at`, `feedback`, `feedback_at` |
| `applications` | Hiring-pipeline tracker: `status` ∈ {applied, phone_screen, interview, offer, rejected, withdrawn} |
| `cover_letters` | AI-generated letters cached for 30 days per `(user_id, job_id)` |
| `events` | Immutable audit trail of every pipeline action |
| `seen_jobs` | Legacy table kept for backward-compat migration; no longer written to |

JSON list columns use a mixin (`_JSONListMixin`) that serializes Python lists to JSON text for SQLite portability. Accessors on the model (`sub.keywords`, `sub.locations`, …) transparently marshal between text and list.

---

## Admin Dashboard

`gosha/web/app.py` is a tiny FastAPI app exposing a single admin namespace. Key characteristics:

- **Binds to `127.0.0.1:8080` only** (`docker-compose.yml` uses `network_mode: host`). There is **no authentication** — the network binding is the security.
- **Access via SSH tunnel:** `ssh -L 8080:127.0.0.1:8080 user@server` and browse `http://localhost:8080/admin/`.
- **Routes** (`gosha/web/admin.py`):
  - `GET /admin/` → Jinja2 dashboard with user / subscription / job / delivery stats.
  - `GET /admin/api/stats` → JSON version of the same stats (useful for scripting).
- **Security headers middleware** — adds `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`.

The admin container shares the same image as `job-bot`; its command override runs uvicorn against `gosha.web.app:app` instead of `main.py`.

---

## Semantic Matching

`gosha/matching.py` defines a `SemanticMatcher` class that lazily loads a sentence-transformers model (default `all-mpnet-base-v2`). It:

1. Encodes a subscription query string built from `keywords + locations + experience_levels` into a normalized embedding.
2. Batch-encodes candidate job texts (`title + company + description`) into embeddings.
3. Computes cosine similarity and keeps jobs above `SEMANTIC_THRESHOLD` (default `0.40`).

If `sentence-transformers` is not installed or `USE_SEMANTIC_MATCHING` is `false`, the pipeline silently falls back to regex title matching and every match gets a score of `1.0`.

**Tuning tips:**

- Lower the threshold (`0.30`) if you want more matches at the cost of relevance.
- Raise it (`0.50+`) for very tight matching.
- Use a smaller model (`all-MiniLM-L6-v2`) for faster inference on low-spec hardware.

---

## Cover Letter Generation

`gosha/cover_letter.py` handles CV upload, Gemini calls, and caching.

**CV storage:** Plain text in `data/cvs/{user_id}.txt`. Extraction:

- **PDF** — `pymupdf` (fitz) with light cleaning (removes LaTeX residue, glyph tokens, control characters).
- **DOCX** — minimal zip/XML parsing; no `python-docx` dependency.
- **TXT/MD** — read directly.
- Max file size is enforced at the upload path.

**Gemini call:** The generator builds a prompt containing the CV + job details (title, company, location, salary, first 3000 chars of description) and targets a 250–350 word output. It retries through a fallback list of Gemini model IDs so a single model being unavailable doesn't break the feature.

**Caching:** Every successful generation is stored in the `cover_letters` table. Subsequent requests for the same `(user_id, job_id)` return the cached version for 30 days. The monthly quota counts unique generations within the current calendar month; a cached re-request does not consume quota.

---

## SSH Tunnel Proxy Rotation

`gosha/ssh_tunnels.py` spawns one `ssh -D 108X` process per configured VPS. Each tunnel:

- Runs with `ServerAliveInterval=30` and `ServerAliveCountMax=3` so dead connections fail fast.
- Exposes a SOCKS5 proxy on `127.0.0.1:1080+index`.
- Is tracked by a `TunnelProcess` object with health state.

`SSHTunnelManager.active_proxies()` returns the currently-usable list. The scraper picks one at random per call. A scheduled health-check job calls `check_and_restart()` every 5 minutes, respawning dead processes.

**Why tunnels?** LinkedIn and Glassdoor aggressively rate-limit and soft-ban single source IPs, especially from datacenter ranges. Rotating through residential-or-cloud egress points keeps the scraper alive long-term.

---

## Database Migrations

`gosha/migrate.py` is a hand-rolled, idempotent migration runner that executes before `Base.metadata.create_all()` on every startup. It handles:

1. **Column adds** — `users.tier`, `subscriptions.remote_ok`, etc. Skipped if already present.
2. **Old → new subscription schema** — older versions stored a single `keyword` + `location` string per subscription. If those columns exist, the migrator copies them into the new JSON-list columns and makes the old ones nullable (SQLite requires a table rebuild for column-nullability changes, which the migrator does in a single transaction).
3. **Legacy `seen_jobs` → `user_jobs`** — creates stub `jobs` rows for any URL still referenced by `seen_jobs`, then maps old delivery history into the new `user_jobs` table so users don't get the same posting twice after upgrade.

All of this runs inside one transaction and is safe to re-run. There's no Alembic, intentionally — the migration surface is small and a single Python file is easier to reason about for a self-hoster.

---

## Development

### Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

Test files in `tests/` cover:

- `test_models.py` — model creation, uniqueness, relationships
- `test_filters.py` — keyword expansion, location normalization, filter functions
- `test_pipeline.py` — scrape/match/deliver stage logic
- `test_queue.py` — `enqueue_delivery`, batch operations
- `test_matching.py` — semantic matcher edge cases
- `test_feedback.py` — profile building and score adjustment
- `test_delivery.py` — embed building and DM dispatch
- `test_events.py` — event emit/query
- `test_migrate.py` — old → new schema migrations
- `test_web.py` — admin dashboard routes and stats API

### Dependencies at a glance

From `requirements.txt`:

| Category | Packages |
|---|---|
| Discord | `discord.py` |
| Scraping | `python-jobspy`, `pandas`, `pysocks` |
| Database | `sqlalchemy`, `aiosqlite` (optional `asyncpg` for Postgres) |
| Scheduler | `apscheduler` |
| Semantic | `sentence-transformers` (optional) |
| Web | `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `itsdangerous` |
| AI | `httpx` (Gemini), `pymupdf` (PDF parsing) |
| Misc | `numpy`, `python-dotenv` |

### Coding style

- `from __future__ import annotations` everywhere — PEP 604 types, lazy evaluation.
- Pure functions in `gosha/filters.py`, `gosha/matching.py` — no DB or IO.
- IO-heavy code in `gosha/pipeline.py`, `gosha/scraper.py`, `gosha/bot.py`.
- Tests target the pure modules most heavily.

---

## Troubleshooting

### "I'm not receiving any DMs"

Check **Server Settings → Privacy Settings → Allow direct messages from server members**. Discord silently drops DMs from bots in servers where this is off.

### `/quickstart` says I already have subscriptions

Quickstart refuses to create a subscription if you already have one. Use `/my_searches` to inspect them or `/subscribe` to add more.

### Bot receives jobs but they're irrelevant

- Use `/edit id:… exclude: sales, marketing, nursing` to drop noisy categories.
- Lower the noise with a tighter keyword (e.g. `software engineer intern` instead of `internship`).
- Click **Not Relevant** on a few jobs — after 3+ ratings your personal profile kicks in.
- Tune `SEMANTIC_THRESHOLD` up (e.g. `0.50`) if semantic matching is too loose for you.

### Scrape logs show `Glassdoor: Error encountered in API response`

Glassdoor's anonymous API is flaky and/or regionally blocked. This is a known upstream issue in JobSpy. LinkedIn and Indeed will still return results — Glassdoor acts as a bonus source when it's up.

### SSH tunnel won't start

Check that the key exists at the path configured in `VPS_N_KEY` (inside the container — the `./keys:/home/app/.ssh:ro` bind mount makes them available). `chmod 600` the key on the host. Watch `docker compose logs job-bot` during startup; each tunnel prints its result.

### Migrations fail after a git pull

Back up `data/jobs.db`, then let the migrator run again on restart. If it still fails, open an issue with the full traceback — the migrator is intentionally simple and usually a clear SQL error points to the cause.

### Admin dashboard returns 404

The admin app is mounted under `/admin/` — visit `http://localhost:8080/admin/`, not `/`. If you forgot the trailing slash, FastAPI may return 404 depending on redirects.

---

## Project Layout

```
autojobGOSHA/
├── main.py                    # Entry shim → gosha.main.main()
├── Dockerfile                 # python:3.11-slim + openssh-client + app user
├── docker-compose.yml         # job-bot + admin, both network_mode: host
├── requirements.txt           # Runtime deps
├── requirements-dev.txt       # Test deps
├── pytest.ini                 # Test config
│
├── gosha/
│   ├── main.py                # Startup sequence, scheduler wiring
│   ├── config.py              # Settings dataclass, env parsing, VPS config
│   ├── env.example            # Template .env
│   │
│   ├── bot.py                 # Discord bot + all slash commands
│   ├── views.py               # Persistent button views (feedback, cover letter)
│   │
│   ├── models.py              # SQLAlchemy ORM models + tier limits
│   ├── database.py            # Async engine, session factory, init_db
│   ├── migrate.py             # Hand-rolled idempotent migrations
│   │
│   ├── pipeline.py            # 3-stage scrape/match/deliver pipeline
│   ├── scraper.py             # JobSpy wrapper + proxy rotation
│   ├── filters.py             # Keyword expansion, location aliases, regex filters
│   ├── matching.py            # SemanticMatcher (sentence-transformers)
│   ├── feedback.py            # UserPreferenceProfile from feedback history
│   ├── delivery.py            # DM embed builder + send logic
│   ├── queue.py               # user_jobs helpers (enqueue, mark delivered)
│   │
│   ├── events.py              # Event store (audit trail)
│   ├── cover_letter.py        # CV extraction + Gemini cover letter gen
│   ├── ssh_tunnels.py         # SSHTunnelManager + health check
│   │
│   └── web/
│       ├── app.py             # FastAPI app (localhost only)
│       └── admin.py           # /admin/ routes, stats API
│
├── tests/                     # Pytest suite
├── data/                      # SQLite DB, CV uploads (created at runtime)
└── keys/                      # SSH private keys for tunnels (mount)
```

---

## License & Credits

- Built on top of [JobSpy](https://github.com/Bunsly/JobSpy) for scraping, [discord.py](https://github.com/Rapptz/discord.py) for the bot, [sentence-transformers](https://www.sbert.net/) for semantic matching, [FastAPI](https://fastapi.tiangolo.com/) for the admin dashboard, and Google's [Gemini API](https://ai.google.dev/) for cover letters.
- Project name **GOSHA** is the internal codename; the Discord bot username is typically **JobHunter**.
