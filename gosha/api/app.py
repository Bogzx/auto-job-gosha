"""FastAPI application factory for the public web API."""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from gosha.api.deps import ApiError, current_user, is_admin
from gosha.api.schemas import MeOut
from gosha.models import User

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


_HTTP_CODES = {
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "file_too_large",
    422: "invalid_request",
    429: "rate_limited",
}


def create_app() -> FastAPI:
    from gosha.config import load_web_settings

    load_web_settings()  # fail fast when required env vars are missing

    app = FastAPI(
        title="GOSHA Jobs API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError):
        return _error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error_handler(request: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "error")
        return _error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        return _error_response(422, "invalid_request", str(exc.errors()[:3]))

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        log.exception("Unhandled API error on %s", request.url.path)
        return _error_response(500, "internal_error", "Something went wrong on our side.")

    @app.get(f"{API_PREFIX}/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get(f"{API_PREFIX}/meta")
    async def meta() -> dict:
        """Static vocabulary for search-form suggestions."""
        from gosha.filters import KEYWORD_EXPANSIONS, LOCATION_ALIASES

        return {
            "smart_keywords": sorted(KEYWORD_EXPANSIONS.keys()),
            "locations": sorted(LOCATION_ALIASES.keys()),
            "experience_levels": ["intern", "junior", "mid", "senior", "any"],
            "sources": ["indeed", "linkedin", "glassdoor"],
        }

    @app.get(f"{API_PREFIX}/me", response_model=MeOut)
    async def me(user: User = Depends(current_user)) -> MeOut:
        from gosha.cover_letter import load_cv

        return MeOut(
            id=user.id,
            discord_id=str(user.discord_user_id),
            username=user.username,
            avatar_url=user.avatar_url,
            tier=user.tier,
            in_guild=user.in_guild,
            has_cv=load_cv(user.id) is not None,
            is_admin=is_admin(user),
        )

    _mount_routers(app)
    return app


def _mount_routers(app: FastAPI) -> None:
    """Mount feature routers; each module exposes `router`."""
    # Imported lazily so a syntax error in one feature surfaces clearly
    # and the skeleton stays importable while features are built out.
    from importlib import import_module

    for module_name in (
        "auth",
        "jobs",
        "feed",
        "applications",
        "subscriptions",
        "cv",
        "cover_letters",
        "analytics",
        "admin",
    ):
        try:
            module = import_module(f"gosha.api.{module_name}")
        except ModuleNotFoundError:
            continue  # feature not built yet
        app.include_router(module.router, prefix=API_PREFIX)
