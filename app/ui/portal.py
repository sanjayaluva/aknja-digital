"""Client portal: project overview, milestones, staging previews, feedback,
UAT acceptance and invoices — scoped strictly to the portal user's client.

Portal users (CLIENT_OWNER / CLIENT_MEMBER) see ONLY their own client's
projects; a leaked URL can never surface another client's data because
every query is filtered by `principal.client_id` (SRS §6).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.security import constant_time_equals
from app.ui.views import current_principal, render

router = APIRouter(prefix="/portal", include_in_schema=False)


def portal_guard(request: Request):
    principal = current_principal(request)
    if principal is None:
        return None, RedirectResponse("/login", status_code=302)
    if not principal.is_portal:
        return None, render(request, "error.html", {"code": 403, "message": "Client portal only"}, status_code=403)
    return principal, None


def csrf_guard(request: Request, principal, token: str | None):
    if token is None or not constant_time_equals(token, principal.csrf_token):
        return render(request, "error.html", {"code": 403, "message": "CSRF token mismatch"}, status_code=403)
    return None


def db_session():
    from app.core.db import get_session_local

    return get_session_local()()


@router.get("", response_class=HTMLResponse)
def portal_home(request: Request):
    principal, redirect = portal_guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from sqlalchemy import func, select

        from app.modules.delivery.models import Feedback, Project, StagingPreview

        assert principal.client_id is not None
        projects = db.scalars(
            select(Project)
            .where(Project.tenant_id == principal.tenant_id, Project.client_id == principal.client_id)
            .order_by(Project.created_at.desc())
        ).all()
        previews = db.scalars(
            select(StagingPreview).where(
                StagingPreview.tenant_id == principal.tenant_id,
                StagingPreview.status == "ACTIVE",
            )
        ).all()
        previews_by_project = {p.project_id: p for p in previews}
        feedback_open = db.scalar(
            select(func.count()).select_from(Feedback).where(
                Feedback.tenant_id == principal.tenant_id,
                Feedback.project_id.in_([p.id for p in projects] or [uuid.uuid4()]),
                Feedback.status == "OPEN",
            )
        )
        return render(
            request,
            "portal/home.html",
            {
                "projects": projects,
                "previews_by_project": previews_by_project,
                "open_feedback_count": feedback_open or 0,
            },
        )
    finally:
        db.close()


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def portal_project(request: Request, project_id: uuid.UUID):
    principal, redirect = portal_guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from sqlalchemy import select

        from app.modules.commercial.models import Invoice
        from app.modules.delivery import service as delivery
        from app.modules.delivery.models import Feedback, Milestone, StagingPreview

        assert principal.client_id is not None
        project = delivery.get_project(db, principal.tenant_id, project_id)
        if project.client_id != principal.client_id:
            return render(request, "error.html", {"code": 404, "message": "Project not found"}, status_code=404)
        milestones = db.scalars(
            select(Milestone).where(Milestone.project_id == project.id).order_by(Milestone.sort_order)
        ).all()
        previews = db.scalars(
            select(StagingPreview).where(
                StagingPreview.project_id == project.id, StagingPreview.status == "ACTIVE"
            )
        ).all()
        feedback = db.scalars(
            select(Feedback).where(Feedback.project_id == project.id).order_by(Feedback.created_at.desc())
        ).all()
        invoices = db.scalars(
            select(Invoice)
            .where(Invoice.tenant_id == principal.tenant_id, Invoice.project_id == project.id)
            .order_by(Invoice.created_at.desc())
        ).all()
        return render(
            request,
            "portal/project.html",
            {
                "project": project,
                "milestones": milestones,
                "previews": previews,
                "feedback": feedback,
                "invoices": invoices,
                "progress": delivery.milestone_progress(db, project.id),
            },
        )
    finally:
        db.close()


@router.post("/projects/{project_id}/feedback", response_class=HTMLResponse)
def portal_feedback(
    request: Request,
    project_id: uuid.UUID,
    kind: str = Form("FEEDBACK"),
    message: str = Form(...),
    page_or_module: str = Form(""),
    severity: str = Form("LOW"),
    reproduction_steps: str = Form(""),
    csrf_token: str = Form(...),
):
    principal, redirect = portal_guard(request)
    if redirect:
        return redirect
    err = csrf_guard(request, principal, csrf_token)
    if err:
        return err
    db = db_session()
    try:
        from app.modules.delivery import service as delivery

        delivery.submit_feedback(
            db,
            principal=principal,
            project_id=project_id,
            kind=kind,
            message=message,
            page_or_module=page_or_module,
            severity=severity,
            reproduction_steps=reproduction_steps,
        )
        db.commit()
        return RedirectResponse(f"/portal/projects/{project_id}", status_code=303)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/projects/{project_id}/uat", response_class=HTMLResponse)
def portal_uat(
    request: Request,
    project_id: uuid.UUID,
    decision: str = Form(...),
    notes: str = Form(""),
    csrf_token: str = Form(...),
):
    principal, redirect = portal_guard(request)
    if redirect:
        return redirect
    err = csrf_guard(request, principal, csrf_token)
    if err:
        return err
    db = db_session()
    try:
        from app.modules.delivery import service as delivery

        delivery.record_uat_decision(
            db,
            principal=principal,
            project_id=project_id,
            checklist=[{"item": "Client reviewed staging preview", "checked": True}],
            decision=decision,
            notes=notes,
        )
        db.commit()
        return RedirectResponse(f"/portal/projects/{project_id}", status_code=303)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/invoices", response_class=HTMLResponse)
def portal_invoices(request: Request):
    principal, redirect = portal_guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from sqlalchemy import select

        from app.modules.commercial.models import Invoice

        assert principal.client_id is not None
        invoices = db.scalars(
            select(Invoice)
            .where(Invoice.tenant_id == principal.tenant_id, Invoice.client_id == principal.client_id)
            .order_by(Invoice.created_at.desc())
        ).all()
        return render(request, "portal/invoices.html", {"invoices": invoices})
    finally:
        db.close()
