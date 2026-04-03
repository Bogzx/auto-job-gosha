"""Minimal FastAPI app — admin dashboard only, localhost-bound.

No public pages, no OAuth, no user sessions.
Access via SSH tunnel: ssh -L 8080:localhost:8080 user@server
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from gosha.database import _engine, init_db

    if _engine is None:
        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/jobs.db")
        await init_db(db_url)
    yield


app = FastAPI(title="GOSHA Admin", version="1.0.0", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)

from gosha.web.admin import router as admin_router  # noqa: E402
app.include_router(admin_router)


@app.get("/")
async def root():
    return RedirectResponse("/admin/")
