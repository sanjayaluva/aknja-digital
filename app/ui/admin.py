"""Admin UI routes: operations + system control screens (docs/12).

Server-rendered HTML with HTMX for interactions. Every screen defines its
loading/empty/error states through the shared partials.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_

from app.core.enums import ApprovalStatus, LeadStatus, ProjectLifecycleState, TaskStatus
from app.core.security import constant_time_equals
from app.modules.governance import service as governance
from app.ui.views import current_principal, render

router = APIRouter(prefix="/admin", include_in_schema=False)


def guard(request: Request, write: bool = False):
    """Page-level guard: internal roles only (deny by default)."""
    principal = current_principal(request)
    if principal is None:
        return None, RedirectResponse("/login", status_code=302)
    if not principal.is_internal:
        return None, render(request, "error.html", {"code": 403, "message": "Forbidden"}, status_code=403)
    if write and not principal.can_write:
        return None, render(request, "error.html", {"code": 403, "message": "Read-only role"}, status_code=403)
    return principal, None


def csrf_guard(request: Request, principal, csrf_token: str | None) -> HTMLResponse | None:
    if csrf_token is None or not constant_time_equals(csrf_token, principal.csrf_token):
        return render(request, "error.html", {"code": 403, "message": "CSRF token mismatch"}, status_code=403)
    return None


def db_session():
    from app.core.db import get_session_local

    return get_session_local()()


# ---------------------------------------------------------------- dashboard


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from sqlalchemy import func, select

        from app.modules.commercial.models import Invoice, Proposal
        from app.modules.crm.models import Client, Lead
        from app.modules.delivery.models import Feedback, Project, Task
        from app.modules.ops.settings_service import get_setting
        from app.modules.resources.models import ProviderProduct

        tid = principal.tenant_id
        stats = {
            "leads_open": db.scalar(
                select(func.count()).select_from(Lead).where(
                    Lead.tenant_id == tid,
                    Lead.status.in_(["NEW", "CONTACTED", "QUALIFIED", "DISCOVERY", "PROPOSAL_SENT"]),
                )
            ),
            "clients": db.scalar(
                select(func.count()).select_from(Client).where(Client.tenant_id == tid)
            ),
            "projects_active": db.scalar(
                select(func.count()).select_from(Project).where(
                    Project.tenant_id == tid,
                    Project.lifecycle_state.notin_(["CLOSED", "ARCHIVED"]),
                )
            ),
            "tasks_open": db.scalar(
                select(func.count()).select_from(Task).where(
                    Task.tenant_id == tid, Task.status.notin_(["DONE", "CANCELLED"])
                )
            ),
            "proposals_pending": db.scalar(
                select(func.count()).select_from(Proposal).where(
                    Proposal.tenant_id == tid, Proposal.status == "SENT"
                )
            ),
            "invoices_due_minor": db.scalar(
                select(func.coalesce(func.sum(Invoice.amount_minor - Invoice.paid_amount_minor), 0)).where(
                    Invoice.tenant_id == tid, Invoice.status.in_(["ISSUED", "PARTIALLY_PAID", "OVERDUE"])
                )
            ),
            "feedback_open": db.scalar(
                select(func.count()).select_from(Feedback).where(
                    Feedback.tenant_id == tid, Feedback.status == "OPEN"
                )
            ),
            "provider_products": db.scalar(
                select(func.count()).select_from(ProviderProduct)
                .join(ProviderProduct.account)
                .where(ProviderProduct.account.has(tenant_id=tid))
            ),
        }
        pending = governance.get_pending_approvals(db, tid)
        stop = governance.get_emergency_stop(db)
        projects = db.scalars(
            select(Project).where(Project.tenant_id == tid).order_by(Project.created_at.desc()).limit(8)
        ).all()
        return render(
            request,
            "admin/dashboard.html",
            {
                "stats": stats,
                "pending_approvals": pending,
                "emergency_stop": stop,
                "projects": projects,
                "brand_name": get_setting(db, "brand_name", "Aknja Digital"),
                "zero_cost_mode": True,
            },
        )
    finally:
        db.close()


# ------------------------------------------------------------------- leads


@router.get("/leads", response_class=HTMLResponse)
def leads_page(request: Request):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from app.modules.crm import service as crm

        rows = crm.list_leads(db, principal.tenant_id)
        return render(request, "admin/leads.html", {"leads": rows, "lead_statuses": list(LeadStatus)})
    finally:
        db.close()


@router.post("/leads", response_class=HTMLResponse)
def leads_create(
    request: Request,
    title: str = Form(...),
    source: str = Form("DIRECT"),
    contact_email: str = Form(""),
    budget_minor: int = Form(0),
    feasibility_score: int = Form(0),
    description: str = Form(""),
    csrf_token: str = Form(...),
):
    principal, redirect = guard(request, write=True)
    if redirect:
        return redirect
    err = csrf_guard(request, principal, csrf_token)
    if err:
        return err
    db = db_session()
    try:
        from app.modules.crm import service as crm
        from app.modules.ops.settings_service import get_setting

        threshold = int(get_setting(db, "min_feasibility_score_threshold", 70))
        lead = crm.create_lead(
            db,
            principal=principal,
            title=title,
            source=source,
            description=description,
            contact_email=contact_email,
            budget_minor=budget_minor,
            feasibility_score=feasibility_score,
        )
        governance.record_audit(
            db,
            tenant_id=principal.tenant_id,
            actor_type="USER",
            actor_id=str(principal.user_id),
            action="lead.created",
            resource_type="lead",
            resource_id=str(lead.id),
        )
        _ = threshold
        db.commit()
        return RedirectResponse("/admin/leads", status_code=303)
    finally:
        db.close()


@router.post("/leads/{lead_id}/qualify", response_class=HTMLResponse)
def leads_qualify(
    request: Request,
    lead_id: uuid.UUID,
    to_status: str = Form(...),
    csrf_token: str = Form(...),
):
    principal, redirect = guard(request, write=True)
    if redirect:
        return redirect
    err = csrf_guard(request, principal, csrf_token)
    if err:
        return err
    db = db_session()
    try:
        from app.modules.crm import service as crm

        crm.qualify_lead(
            db, tenant_id=principal.tenant_id, lead_id=lead_id, to_status=LeadStatus(to_status)
        )
        db.commit()
        return RedirectResponse("/admin/leads", status_code=303)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ------------------------------------------------------------------ clients


@router.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from app.modules.crm import service as crm

        return render(request, "admin/clients.html", {"clients": crm.list_clients(db, principal.tenant_id)})
    finally:
        db.close()


@router.post("/clients", response_class=HTMLResponse)
def clients_create(
    request: Request,
    display_name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    csrf_token: str = Form(...),
):
    principal, redirect = guard(request, write=True)
    if redirect:
        return redirect
    err = csrf_guard(request, principal, csrf_token)
    if err:
        return err
    db = db_session()
    try:
        from app.modules.crm import service as crm

        crm.create_client(db, principal=principal, display_name=display_name, email=email, phone=phone)
        db.commit()
        return RedirectResponse("/admin/clients", status_code=303)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ------------------------------------------------------------------ catalog


@router.get("/catalog", response_class=HTMLResponse)
def catalog_page(request: Request, search: str = ""):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from sqlalchemy import select

        from app.modules.catalog.models import ServiceCategory

        categories = db.scalars(
            select(ServiceCategory)
            .where(ServiceCategory.tenant_id == principal.tenant_id)
            .order_by(ServiceCategory.domain, ServiceCategory.sort_order, ServiceCategory.code)
        ).all()
        tree = []
        for category in categories:
            subs = []
            for sub in category.subcategories:
                services = [s for s in sub.services if not search or search.lower() in s.name.lower()]
                if services or not search:
                    subs.append((sub, services))
            if subs:
                tree.append((category, subs))
        return render(request, "admin/catalog.html", {"tree": tree, "search": search})
    finally:
        db.close()


# ----------------------------------------------------------------- projects


@router.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from app.modules.delivery import service as delivery

        return render(
            request,
            "admin/projects.html",
            {"projects": delivery.list_projects(db, principal.tenant_id)},
        )
    finally:
        db.close()


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(request: Request, project_id: uuid.UUID):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from sqlalchemy import select

        from app.modules.delivery import service as delivery
        from app.modules.delivery.models import (
            Feedback,
            Milestone,
            StagingPreview,
            Task,
            UATAcceptance,
        )

        project = delivery.get_project(db, principal.tenant_id, project_id)
        milestones = db.scalars(
            select(Milestone).where(Milestone.project_id == project.id).order_by(Milestone.sort_order)
        ).all()
        tasks = db.scalars(
            select(Task).where(Task.project_id == project.id).order_by(Task.created_at.desc())
        ).all()
        previews = db.scalars(
            select(StagingPreview).where(StagingPreview.project_id == project.id)
        ).all()
        feedback = db.scalars(
            select(Feedback).where(Feedback.project_id == project.id).order_by(Feedback.created_at.desc())
        ).all()
        uat = db.scalars(
            select(UATAcceptance).where(UATAcceptance.project_id == project.id)
        ).all()
        return render(
            request,
            "admin/project_detail.html",
            {
                "project": project,
                "milestones": milestones,
                "tasks": tasks,
                "previews": previews,
                "feedback": feedback,
                "uat_records": uat,
                "progress": delivery.milestone_progress(db, project.id),
                "lifecycle_states": list(ProjectLifecycleState),
                "task_statuses": list(TaskStatus),
            },
        )
    finally:
        db.close()


@router.post("/projects/{project_id}/transition", response_class=HTMLResponse)
def project_transition(
    request: Request, project_id: uuid.UUID, to_state: str = Form(...), csrf_token: str = Form(...)
):
    principal, redirect = guard(request, write=True)
    if redirect:
        return redirect
    err = csrf_guard(request, principal, csrf_token)
    if err:
        return err
    db = db_session()
    try:
        from app.modules.delivery import service as delivery

        delivery.transition_project(
            db,
            tenant_id=principal.tenant_id,
            project_id=project_id,
            to_state=ProjectLifecycleState(to_state),
        )
        db.commit()
        return RedirectResponse(f"/admin/projects/{project_id}", status_code=303)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/projects/{project_id}/tasks", response_class=HTMLResponse)
def project_task_create(
    request: Request,
    project_id: uuid.UUID,
    title: str = Form(...),
    priority: str = Form("MEDIUM"),
    estimate_hours: int = Form(0),
    csrf_token: str = Form(...),
):
    principal, redirect = guard(request, write=True)
    if redirect:
        return redirect
    err = csrf_guard(request, principal, csrf_token)
    if err:
        return err
    db = db_session()
    try:
        from app.modules.delivery import service as delivery

        delivery.create_task(
            db,
            tenant_id=principal.tenant_id,
            project_id=project_id,
            title=title,
            priority=priority,
            estimate_hours=estimate_hours,
        )
        db.commit()
        return RedirectResponse(f"/admin/projects/{project_id}", status_code=303)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/tasks/{task_id}/transition", response_class=HTMLResponse)
def task_transition(
    request: Request, task_id: uuid.UUID, to_status: str = Form(...), csrf_token: str = Form(...)
):
    principal, redirect = guard(request, write=True)
    if redirect:
        return redirect
    err = csrf_guard(request, principal, csrf_token)
    if err:
        return err
    db = db_session()
    try:

        from app.modules.delivery import service as delivery
        from app.modules.delivery.models import Task

        task = db.get(Task, task_id)
        assert task is not None
        delivery.transition_task(
            db, tenant_id=principal.tenant_id, task_id=task_id, to_status=TaskStatus(to_status)
        )
        db.commit()
        return RedirectResponse(f"/admin/projects/{task.project_id}", status_code=303)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/projects/{project_id}/staging-previews", response_class=HTMLResponse)
def staging_preview_create(
    request: Request, project_id: uuid.UUID, url: str = Form(...), csrf_token: str = Form(...)
):
    principal, redirect = guard(request, write=True)
    if redirect:
        return redirect
    err = csrf_guard(request, principal, csrf_token)
    if err:
        return err
    db = db_session()
    try:
        from app.modules.delivery import service as delivery

        delivery.create_staging_preview(
            db, tenant_id=principal.tenant_id, project_id=project_id, url=url
        )
        db.commit()
        return RedirectResponse(f"/admin/projects/{project_id}", status_code=303)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --------------------------------------------------------------- approvals


@router.get("/approvals", response_class=HTMLResponse)
def approvals_page(request: Request):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        pending = governance.get_pending_approvals(db, principal.tenant_id)
        from sqlalchemy import select

        from app.modules.governance.models import ApprovalRequest

        decided = db.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.tenant_id == principal.tenant_id,
                ApprovalRequest.status != ApprovalStatus.PENDING.value,
            )
            .order_by(ApprovalRequest.decided_at.desc().nullslast())
            .limit(20)
        ).all()
        return render(request, "admin/approvals.html", {"pending": pending, "decided": decided})
    finally:
        db.close()


@router.post("/approvals/{approval_id}/decide", response_class=HTMLResponse)
def approvals_decide(
    request: Request,
    approval_id: uuid.UUID,
    decision: str = Form(...),
    note: str = Form(""),
    csrf_token: str = Form(...),
):
    principal, redirect = guard(request, write=True)
    if redirect:
        return redirect
    err = csrf_guard(request, principal, csrf_token)
    if err:
        return err
    db = db_session()
    try:
        request_row = governance.fetch_approval(db, principal.tenant_id, approval_id)
        governance.decide_approval_request(
            db, request=request_row, principal=principal, decision=decision, note=note
        )
        db.commit()
        return RedirectResponse("/admin/approvals", status_code=303)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# -------------------------------------------------------------------- audit


@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from sqlalchemy import select

        from app.modules.governance.models import AuditEvent

        rows = db.scalars(
            select(AuditEvent)
            .where(
                or_(
                    AuditEvent.tenant_id == principal.tenant_id,
                    # system-level events (e.g. auth.login) are recorded with
                    # tenant_id NULL — excluding them hid every login event
                    # from the audit console (found by E2E T-007)
                    AuditEvent.tenant_id.is_(None),
                )
            )
            .order_by(AuditEvent.id.desc())
            .limit(100)
        ).all()
        chain_valid = governance.verify_audit_chain(db)
        return render(request, "admin/audit.html", {"events": rows, "chain_valid": chain_valid})
    finally:
        db.close()


# ----------------------------------------------------------------- settings


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    _, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from app.modules.ops import settings_service

        grouped = settings_service.get_settings_by_category(db)
        protected = {
            "zero_cost_mode": "ZERO_COST_ONLY (protected)",
            "max_approved_monthly_spend_minor": "INR 0 spend ceiling (protected)",
            "paid_fallback_enabled": "Paid fallback disabled (protected)",
        }
        return render(
            request,
            "admin/settings.html",
            {"grouped": grouped, "protected": protected, "saved": request.query_params.get("saved")},
        )
    finally:
        db.close()


@router.post("/settings", response_class=HTMLResponse)
async def settings_save(request: Request):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    if not principal.can_write:
        return render(request, "error.html", {"code": 403, "message": "Read-only role"}, status_code=403)
    form = await request.form()
    err = csrf_guard(request, principal, form.get("csrf_token"))
    if err:
        return err
    db = db_session()
    try:
        import json

        from app.modules.ops import settings_service

        for key in form:
            if key == "csrf_token":
                continue
            raw = form[key]
            value: object
            if isinstance(raw, str):
                try:
                    value = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    if raw.lower() in ("true", "false"):
                        value = raw.lower() == "true"
                    else:
                        value = raw
            else:
                value = raw
            settings_service.update_setting(db, principal=principal, key=key, value=value)
        db.commit()
        return RedirectResponse("/admin/settings?saved=1", status_code=303)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------- providers


@router.get("/providers", response_class=HTMLResponse)
def providers_page(request: Request):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from sqlalchemy import select

        from app.modules.resources.models import ProviderAccount, ProviderProduct

        accounts = db.scalars(
            select(ProviderAccount)
            .where(ProviderAccount.tenant_id == principal.tenant_id)
            # stable UI ordering: heap order otherwise varies between runs
            .order_by(ProviderAccount.provider)
        ).all()
        products = db.execute(
            select(ProviderProduct)
            .join(ProviderAccount, ProviderProduct.account_id == ProviderAccount.id)
            .where(ProviderAccount.tenant_id == principal.tenant_id)
            .order_by(ProviderProduct.category, ProviderProduct.product_key)
        ).scalars().all()
        stop = governance.get_emergency_stop(db)
        return render(
            request,
            "admin/providers.html",
            {"accounts": accounts, "products": products, "emergency_stop": stop},
        )
    finally:
        db.close()


# ------------------------------------------------------------------- tools


@router.get("/ai", response_class=HTMLResponse)
def ai_page(request: Request):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from sqlalchemy import select

        from app.modules.ai.gateway import ToolGateway
        from app.modules.ai.models import AgentCapability, AgentRun
        from app.modules.governance.models import AuditEvent

        capabilities = db.scalars(
            select(AgentCapability).where(AgentCapability.tenant_id == principal.tenant_id)
        ).all()
        runs = db.scalars(
            select(AgentRun)
            .where(AgentRun.tenant_id == principal.tenant_id)
            .order_by(AgentRun.created_at.desc())
            .limit(25)
        ).all()
        tools = ToolGateway(db).list_tools()
        recent_audits = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == principal.tenant_id, AuditEvent.action.like("tool.%"))
            .order_by(AuditEvent.id.desc())
            .limit(10)
        ).all()
        return render(
            request,
            "admin/ai.html",
            {"capabilities": capabilities, "runs": runs, "tools": tools, "recent_tool_audits": recent_audits},
        )
    finally:
        db.close()


# ------------------------------------------------------------------ reports


@router.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from sqlalchemy import func, select

        from app.modules.commercial.models import Invoice
        from app.modules.crm.models import Lead
        from app.modules.delivery.models import Project

        tid = principal.tenant_id
        lead_funnel = db.execute(
            select(Lead.status, func.count()).where(Lead.tenant_id == tid).group_by(Lead.status)
        ).all()
        project_states = db.execute(
            select(Project.lifecycle_state, func.count())
            .where(Project.tenant_id == tid)
            .group_by(Project.lifecycle_state)
        ).all()
        invoice_status = db.execute(
            select(Invoice.status, func.count())
            .where(Invoice.tenant_id == tid)
            .group_by(Invoice.status)
        ).all()
        revenue_minor = db.scalar(
            select(func.coalesce(func.sum(Invoice.paid_amount_minor), 0)).where(Invoice.tenant_id == tid)
        )
        return render(
            request,
            "admin/reports.html",
            {
                "lead_funnel": lead_funnel,
                "project_states": project_states,
                "invoice_status": invoice_status,
                "revenue_minor": revenue_minor or 0,
                "generated_at": "live database query",
            },
        )
    finally:
        db.close()


# ------------------------------------------------------------------ invoices


@router.get("/invoices", response_class=HTMLResponse)
def invoices_page(request: Request):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from app.modules.commercial import service as commercial

        return render(
            request, "admin/invoices.html", {"invoices": commercial.list_invoices(db, principal.tenant_id)}
        )
    finally:
        db.close()
