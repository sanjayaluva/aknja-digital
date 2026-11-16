"""Admin UI routes for the integration credential hub and multi-channel
intake (docs/34, T-027). Split out of admin.py to keep that file navigable;
same guard/csrf/render helpers, same /admin prefix."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.errors import ValidationAppError
from app.ui.admin import csrf_guard, db_session, guard
from app.ui.views import render

router = APIRouter(prefix="/admin", include_in_schema=False)


# --------------------------------------------------- integrations (T-027)

_INTEGRATIONS_FLASH = {
    "ok": "Integration saved.", "status": "Status updated.",
    "tested": "Test finished — see the Last test column.",
    "deleted": "Credential deleted.",
}


@router.get("/integrations", response_class=HTMLResponse)
def integrations_page(request: Request):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from sqlalchemy import select

        from app.modules.integrations import service as integrations
        from app.modules.integrations.models import IntegrationCredential

        creds = db.scalars(
            select(IntegrationCredential)
            .where(IntegrationCredential.tenant_id == principal.tenant_id)
            .order_by(IntegrationCredential.provider_type, IntegrationCredential.provider_key)
        ).all()
        return render(
            request,
            "admin/integrations.html",
            {"creds": creds,
             "hints": {c.id: integrations.masked_hint(c) for c in creds},
             "flash": None, "flash_ok": True, "edit_row": None},
        )
    finally:
        db.close()


@router.post("/integrations/save", response_class=HTMLResponse)
def integrations_save(
    request: Request,
    provider_key: str = Form(...),
    provider_type: str = Form(...),
    name: str = Form(""),
    secrets: str = Form(""),
    config: str = Form("{}"),
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
        import json as _json

        from app.modules.integrations import service as integrations

        try:
            parsed_secrets = _json.loads(secrets) if secrets.strip() else None
            parsed_config = _json.loads(config) if config.strip() else {}
        except _json.JSONDecodeError as exc:
            raise ValidationAppError(f"invalid JSON: {exc}") from exc
        integrations.save_credential(
            db, principal=principal, provider_key=provider_key,
            provider_type=provider_type, name=name,
            secrets=parsed_secrets, config=parsed_config,
        )
        db.commit()
        return RedirectResponse("/admin/integrations?flash=ok", status_code=303)
    finally:
        db.close()


@router.post("/integrations/status", response_class=HTMLResponse)
def integrations_status(
    request: Request,
    credential_id: uuid.UUID = Form(...),
    status: str = Form(...),
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
        from app.modules.integrations import service as integrations

        integrations.set_status(db, principal=principal,
                                credential_id=credential_id, status=status)
        db.commit()
        return RedirectResponse("/admin/integrations?flash=status", status_code=303)
    finally:
        db.close()


@router.post("/integrations/test", response_class=HTMLResponse)
def integrations_test(
    request: Request,
    credential_id: uuid.UUID = Form(...),
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
        from app.modules.integrations import service as integrations

        integrations.test_credential(db, principal=principal,
                                     credential_id=credential_id)
        db.commit()
        return RedirectResponse("/admin/integrations?flash=tested", status_code=303)
    finally:
        db.close()


@router.post("/integrations/delete", response_class=HTMLResponse)
def integrations_delete(
    request: Request,
    credential_id: uuid.UUID = Form(...),
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
        from app.modules.integrations import service as integrations

        integrations.delete_credential(db, principal=principal,
                                       credential_id=credential_id)
        db.commit()
        return RedirectResponse("/admin/integrations?flash=deleted", status_code=303)
    finally:
        db.close()


# ------------------------------------------------------------ intake (T-027)


@router.get("/intake", response_class=HTMLResponse)
def intake_page(request: Request, message_id: str = "", flash: str = ""):
    principal, redirect = guard(request)
    if redirect:
        return redirect
    db = db_session()
    try:
        from sqlalchemy import select

        from app.modules.intake.models import IntakeMessage

        messages = db.scalars(
            select(IntakeMessage)
            .where(IntakeMessage.tenant_id == principal.tenant_id)
            .order_by(IntakeMessage.created_at.desc())
            .limit(50)
        ).all()
        detail = None
        if message_id:
            detail = db.get(IntakeMessage, uuid.UUID(message_id))
            if detail is not None and detail.tenant_id != principal.tenant_id:
                detail = None
        return render(
            request,
            "admin/intake.html",
            {"messages": messages, "detail": detail,
             "flash": _INTEGRATIONS_FLASH.get(flash) or None, "flash_ok": True},
        )
    finally:
        db.close()


@router.post("/intake/submit", response_class=HTMLResponse)
def intake_submit(
    request: Request,
    channel: str = Form("MANUAL"),
    sender: str = Form(""),
    content: str = Form(...),
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
        from app.modules.intake import service as intake

        msg = intake.submit_intake_message(
            db, principal=principal, channel=channel, sender=sender,
            content=content,
        )
        db.commit()
        return RedirectResponse(
            f"/admin/intake?message_id={msg.id}&flash=ok", status_code=303)
    finally:
        db.close()


@router.post("/intake/reprocess", response_class=HTMLResponse)
def intake_reprocess(
    request: Request,
    message_id: uuid.UUID = Form(...),
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
        from app.modules.intake import service as intake

        msg = intake.reprocess_intake_message(
            db, principal=principal, message_id=message_id)
        db.commit()
        return RedirectResponse(
            f"/admin/intake?message_id={msg.id}&flash=ok", status_code=303)
    finally:
        db.close()
