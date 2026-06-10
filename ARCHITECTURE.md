# GOSHA Architecture

Clean-architecture layering, pragmatic edition. The dependency rule points
inward: outer layers import inner ones, never the reverse.

```
┌──────────────────────────────────────────────────────────────────┐
│  Interface adapters (outermost)                                  │
│   gosha/api/        FastAPI routers — HTTP in/out only           │
│   gosha/bot.py      Discord slash commands + views               │
│   gosha/scrapers/   job-board adapters (one per source)          │
│   gosha/llm.py      LLM provider port (OpenRouter / Gemini)      │
│   web/              React SPA (talks to gosha/api over JSON)     │
├──────────────────────────────────────────────────────────────────┤
│  Application / use cases                                         │
│   gosha/services/   business rules + transactions                │
│     jobs, applications, subscriptions, cv, cover_letters,        │
│     users, admin_stats                                           │
│   gosha/pipeline.py scheduled scrape→match→deliver cycle         │
│   gosha/recommend.py personalized feed ranking                   │
│   gosha/embeddings.py vector generation/storage                  │
│   gosha/outbox.py   web→Discord message bridge                   │
│   gosha/cover_letter.py CV storage + letter generation           │
├──────────────────────────────────────────────────────────────────┤
│  Domain (innermost — pure, no IO)                                │
│   gosha/domain/errors.py  business exceptions                    │
│   gosha/filters.py        keyword/location/relevance logic       │
│   gosha/matching.py       embedding similarity primitives        │
│   gosha/feedback.py       preference profiles                    │
├──────────────────────────────────────────────────────────────────┤
│  Infrastructure                                                  │
│   gosha/models.py    SQLAlchemy entities (pragmatic: shared      │
│                      across layers instead of separate DTOs)     │
│   gosha/database.py  engine/session factory                      │
│   gosha/migrate.py   idempotent schema migrations                │
│   gosha/config.py    env-based settings                          │
└──────────────────────────────────────────────────────────────────┘
```

## Rules

1. **Services raise domain errors** (`gosha/domain/errors.py`), never HTTP
   exceptions. The API layer maps codes to status codes in
   `gosha/api/app.py::_DOMAIN_STATUS`; the bot maps them to friendly
   messages.
2. **Routers are thin**: parse request → call service → serialize schema.
   No SQLAlchemy queries inside `gosha/api/` routers (session/auth plumbing
   in `deps.py` is the one exception).
3. **External systems get ports**: LLM providers behind `llm.generate()`,
   job boards behind `scrapers.base.BaseScraper`, Discord delivery behind
   `outbox`/`delivery`. Swapping a provider touches one file.
4. **Scraper adapters never raise** out of `search()` — a dead source logs
   and returns `[]`; the cycle continues.
5. **Pragmatic compromises, on purpose**: SQLAlchemy models double as
   domain entities (no separate DTO layer at this scale), and `bot.py`
   predates the services layer — new bot features should call services,
   existing commands migrate opportunistically.

## Processes

Three deployables share the `gosha` package and one Postgres database:
- **bot** — Discord gateway + APScheduler (scrape cycle, outbox poller,
  embedding backfill, dead-link checks)
- **api** — uvicorn FastAPI serving `/api/v1` for the SPA
- **caddy** — serves the built SPA, terminates TLS, proxies `/api`

The web app and bot never call each other: the database (incl. the
`outbox` table) is the only contract between them.
