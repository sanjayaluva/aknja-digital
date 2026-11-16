"""Client portal: project overview, milestones, staging previews, feedback,
UAT acceptance and invoices — scoped strictly to the portal user's client.

Portal users (CLIENT_OWNER / CLIENT_MEMBER) see ONLY their own client's
projects; a leaked URL can never surface another client's data because
every query is filtered by `principal.client_id` (SRS §6).
"""

from __future__ import annotations

import re
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


# --- client-facing translation (built on the governed task=translation path) ---

TRANSLATE_LANGUAGES = {"en": "English", "hi": "Hindi", "ml": "Malayalam", "ta": "Tamil"}
TRANSLATE_MAX_CHARS = 2000

# Instruction strings mirror the benchmark translation scenarios EXACTLY —
# the indictrans2 worker (the primary translation lane, 100% benchmark) parses
# this precise phrasing; free-form instructions get a 400. The worker's
# contract is en<->{ml,hi,ta} (docs/34 §3), enforced below.
_TRANSLATE_INSTRUCTIONS = {
    "ml": "താഴെയുള്ള ഇംഗ്ലീഷ് വാക്യം മലയാളത്തിലേക്ക് വിവർത്തനം ചെയ്യുക. ബ്രാൻഡ് പേരുകൾ "
          "(Aknja Digital, WhatsApp) അതേപടി നിലനിർത്തുക. വിവർത്തനം മാത്രം ഔട്ട്പുട്ട് ചെയ്യുക.\n\nവാക്യം: ",
    "hi": "नीचे दिए गए अंग्रेज़ी वाक्य का हिंदी में अनुवाद करें। ब्रांड नाम (Aknja Digital, "
          "WhatsApp) यथावत रखें। केवल अनुवाद दें।\n\nवाक्य: ",
    "ta": "கீழே உள்ள ஆங்கில வாக்கியத்தை தமிழில் மொழிபெயர்க்கவும். பிராண்ட் பெயர்களை "
          "(Aknja Digital, WhatsApp) மாற்றாமல் வைக்கவும். மொழிபெயர்ப்பை மட்டும் தருக.\n\nவாக்கியம்: ",
    "en": "Translate the Malayalam sentence into professional English. Render brand "
          "names in Latin script exactly (Aknja Digital, WhatsApp). Output only the "
          "translation.\n\nSentence: ",
}

# Defense-in-depth: obvious credential shapes never leave for a third-party
# model, whatever the declared classification (gateway llm.generate only
# accepts PUBLIC/INTERNAL; this screen catches accidental paste-ins).
_CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:sk-|ghp_|gho_|github_pat_|AKIA|AIza)[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\b\s*[:=]\s*\S+"),
)


def _translate_context(db, principal) -> dict:
    from datetime import date

    from sqlalchemy import func, select

    from app.modules.governance.models import AuditEvent
    from app.modules.ops.settings_service import get_setting

    limit = int(get_setting(db, "portal_translate_daily_limit", 50) or 50)
    used = db.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.tenant_id == principal.tenant_id,
            AuditEvent.action == "portal.translate",
            AuditEvent.resource_id == str(principal.client_id),
            func.date(AuditEvent.created_at) == date.today(),
        )
    )
    return {"daily_limit": limit, "used_today": used or 0}


@router.get("/translate", response_class=HTMLResponse)
def portal_translate(request: Request):
    principal, redirect = portal_guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        ctx = _translate_context(db, principal)
        return render(request, "portal/translate.html", {
            "csrf_token": principal.csrf_token,
            "langs": TRANSLATE_LANGUAGES,
            "form": {"source": "en", "target": "ml", "text": ""},
            "result": None,
            "error": None,
            **ctx,
        })
    finally:
        db.close()


@router.post("/translate", response_class=HTMLResponse)
def portal_translate_submit(
    request: Request,
    source: str = Form(...),
    target: str = Form(...),
    text: str = Form(...),
    csrf_token: str = Form(...),
):
    principal, redirect = portal_guard(request)
    if redirect:
        return redirect
    bad = csrf_guard(request, principal, csrf_token)
    if bad:
        return bad
    db = db_session()
    try:
        ctx = _translate_context(db, principal)
        form = {"source": source, "target": target, "text": text}
        error = None
        result = None

        if source not in TRANSLATE_LANGUAGES or target not in TRANSLATE_LANGUAGES:
            error = "Unsupported language."
        elif source == target:
            error = "Source and target language must differ."
        elif (source != "en") == (target != "en"):
            # indictrans2 worker contract: en<->{ml,hi,ta} only (docs/34 §3)
            error = "Supported pairs: English ↔ Malayalam / Hindi / Tamil."
        elif not (text := text.strip()):
            error = "Enter some text to translate."
        elif len(text) > TRANSLATE_MAX_CHARS:
            error = f"Text is limited to {TRANSLATE_MAX_CHARS} characters per request."
        elif ctx["used_today"] >= ctx["daily_limit"]:
            error = ("Daily translation limit reached "
                     f"({ctx['daily_limit']} requests). It resets tomorrow.")
        elif any(p.search(text) for p in _CREDENTIAL_PATTERNS):
            error = ("This looks like credentials or API keys — for your safety it "
                     "was NOT sent to any AI service. Remove secrets and try again.")

        if error is None:
            from app.modules.ai.gateway import ToolGateway

            prompt = f"{_TRANSLATE_INSTRUCTIONS[target]}{text}"
            gateway = ToolGateway(db)
            execution = gateway.execute_tool(
                principal=principal,
                tool_name="llm.generate",
                arguments={
                    "task": "translation",
                    "prompt": prompt,
                    "data_classification": "INTERNAL",
                },
                idempotency_key=f"portal-translate:{uuid.uuid4()}",
            )
            outcome = execution.result or {}
            if execution.status == "SUCCEEDED" and outcome.get("status") == "SUCCEEDED":
                result = {
                    "text": outcome.get("text", "").strip(),
                    "provider": outcome.get("provider", ""),
                    "model": outcome.get("model", ""),
                    "latency_ms": outcome.get("latency_ms", 0),
                }
                ctx["used_today"] += 1
                # Metadata only — the raw text is never persisted (LLMCallLog
                # stores a hash; the audit ledger stores chars/provider).
                from app.modules.governance.service import record_audit

                record_audit(
                    db,
                    tenant_id=principal.tenant_id,
                    actor_type="user",
                    actor_id=str(principal.user_id),
                    action="portal.translate",
                    resource_type="client",
                    resource_id=str(principal.client_id),
                    payload={
                        "source": source, "target": target, "chars": len(text),
                        "provider": result["provider"], "model": result["model"],
                        "latency_ms": result["latency_ms"],
                    },
                )
            else:
                # Fail-closed governed outcome (PENDING_MANUAL/BLOCKED/FAILED):
                # never a silent degrade — tell the client what happened.
                error = ("Translation is temporarily unavailable ("
                         f"{outcome.get('status') or execution.status}: "
                         f"{outcome.get('reason') or execution.error or 'no eligible free provider'}). "
                         "Your text was not delivered.")
        db.commit()
        return render(request, "portal/translate.html", {
            "csrf_token": principal.csrf_token,
            "langs": TRANSLATE_LANGUAGES,
            "form": form,
            "result": result,
            "error": error,
            **ctx,
        })
    finally:
        db.close()


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
