"""Server-rendered UI: shared view helpers and the auth surface."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import get_settings
from app.core.db import get_session_local

router = APIRouter(include_in_schema=False)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = None


def get_templates(request: Request):
    return request.app.state.templates


def render(request: Request, template: str, context: dict | None = None, status_code: int = 200) -> HTMLResponse:
    tpl = get_templates(request)
    ctx = {
        "request": request,
        "app_name": get_settings().app_name,
        "principal": getattr(request.state, "principal", None),
    }
    ctx.update(context or {})
    return tpl.TemplateResponse(request, template, ctx, status_code=status_code)


def current_principal(request: Request):
    """Resolve principal from the session cookie (None when anonymous)."""
    db = get_session_local()()
    try:
        token = request.cookies.get("aknja_session")
        if not token:
            return None
        from app.modules.identity.service import resolve_principal

        return resolve_principal(db, token)
    finally:
        db.close()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    principal = current_principal(request)
    if principal is None:
        return RedirectResponse("/login", status_code=302)
    if principal.is_portal:
        return RedirectResponse("/portal", status_code=302)
    return RedirectResponse("/admin", status_code=302)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    principal = current_principal(request)
    if principal is not None:
        return RedirectResponse("/", status_code=302)
    return render(request, "auth/login.html")


@router.get("/healthz-page", response_class=HTMLResponse, include_in_schema=False)
def health_page(request: Request):
    return render(request, "health.html", {"env": get_settings().app_env})
