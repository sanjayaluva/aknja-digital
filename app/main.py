"""Aknja Digital — FastAPI application factory.

Modular monolith (ADR-001/ADR-002): FastAPI + SQLAlchemy 2 + PostgreSQL,
server-rendered HTML + HTMX + Alpine.js frontend. No external provider is
required for core operation (zero-cost baseline, SRS §14).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, request_id_ctx

API_PREFIX = "/api/v1"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Request ID + structured access log + baseline security headers."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        started = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = request_id
            response.headers["x-content-type-options"] = "nosniff"
            response.headers["x-frame-options"] = "DENY"
            response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
            if get_settings().is_production:
                response.headers["strict-transport-security"] = "max-age=63072000; includeSubDomains"
            return response
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            import logging

            logging.getLogger("aknja.access").info(
                "request",
                extra={
                    "ctx": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": status_code,
                        "ms": elapsed_ms,
                    }
                },
            )
            request_id_ctx.reset(token)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    # Verify database connectivity at startup (fail fast).
    engine = get_engine()
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    # RequestContextMiddleware added LAST => OUTERMOST (request id, access
    # log, security headers wrap everything, including 503 freeze responses);
    # the maintenance write-freeze check runs inside it.
    from app.modules.ops.maintenance import MaintenanceModeMiddleware

    app.add_middleware(MaintenanceModeMiddleware)
    app.add_middleware(RequestContextMiddleware)

    # --- Health endpoints (docs/11 contract) ---
    @app.get("/health/live", tags=["health"])
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready", tags=["health"])
    def ready() -> JSONResponse:
        from sqlalchemy import text

        engine = get_engine()
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return JSONResponse({"status": "ready", "database": "ok"})
        except Exception:
            return JSONResponse(
                status_code=503, content={"status": "not_ready", "database": "unreachable"}
            )

    @app.get("/healthz", tags=["health"], include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "env": settings.app_env}

    @app.head("/healthz", tags=["health"], include_in_schema=False)
    def healthz_head() -> Response:
        # External uptime monitors (UptimeRobot et al.) probe with HEAD;
        # a 405 here reads as "site down" (observed live 2026-11-15, T-024).
        return Response(status_code=200)

    # --- API v1 routers ---
    from app.api.v1 import ai, auth, catalog, commercial, crm, delivery, governance, resources
    from app.api.v1 import settings as settings_api

    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(crm.router, prefix=API_PREFIX)
    app.include_router(catalog.router, prefix=API_PREFIX)
    app.include_router(commercial.router, prefix=API_PREFIX)
    app.include_router(delivery.router, prefix=API_PREFIX)
    app.include_router(governance.router, prefix=API_PREFIX)
    app.include_router(resources.router, prefix=API_PREFIX)
    app.include_router(ai.router, prefix=API_PREFIX)
    app.include_router(settings_api.router, prefix=API_PREFIX)

    # --- Static assets + server-rendered UI ---
    from pathlib import Path

    base_dir = Path(__file__).resolve().parent
    app.mount("/static", StaticFiles(directory=base_dir / "static"), name="static")

    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    app.state.templates = templates

    from app.ui.admin import router as admin_router
    from app.ui.admin_integrations import router as admin_integrations_router
    from app.ui.hooks import router as hooks_router
    from app.ui.portal import router as portal_router
    from app.ui.views import router as ui_router

    app.include_router(ui_router)
    app.include_router(admin_router)
    app.include_router(admin_integrations_router)
    app.include_router(hooks_router)
    app.include_router(portal_router)

    return app


app = create_app()
