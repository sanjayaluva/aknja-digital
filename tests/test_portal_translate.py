"""Client-facing portal translation (T-025): governed task=translation path
through the ToolGateway (privacy/data-class gates, quota, audit) with a
client-facing daily limit and a credential screen.
"""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy import select

from app.core.security import canonical_payload_hash
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, AuthClient

TEXT_EN = "Aknja Digital will launch the new client portal next Friday."


def _setup_portal(db, app, seed, monkeypatch) -> AuthClient:
    """Client owner + an eligible indictrans2 product; inference mocked."""
    from app.core.enums import UserRole
    from app.core.security import utcnow
    from app.modules.crm import service as crm
    from app.modules.identity import service as identity
    from app.modules.identity.service import Principal
    from app.modules.resources.candidates import register_candidate_providers
    from app.modules.resources.models import ProviderAccount, ProviderProduct
    from app.modules.resources.service import record_snapshot

    register_candidate_providers(db, seed.tenant.id)

    principal = Principal(
        user_id=seed.admin.id, email=seed.admin.email, tenant_id=seed.tenant.id,
        role=UserRole.SUPER_ADMIN, client_id=None, session_id=seed.admin.id,
        csrf_token="seed",
    )
    client_row = crm.create_client(db, principal=principal, display_name="Trans Co")
    db.commit()

    account = db.query(ProviderAccount).filter(
        ProviderAccount.tenant_id == seed.tenant.id,
        ProviderAccount.provider == "indictrans2",
    ).one()
    product = db.query(ProviderProduct).filter(
        ProviderProduct.account_id == account.id
    ).one()
    account.last_verified_at = utcnow()
    product.allowance = 100
    product.enabled = True
    record_snapshot(db, product, locally_metered=0)
    db.commit()

    identity.create_user(
        db, email="trans-owner@example.com", password="TransPass#1",
        tenant_id=seed.tenant.id, role=UserRole.CLIENT_OWNER, client_id=client_row.id,
    )
    db.commit()

    class _Result:
        attempts: ClassVar[list] = []
        status = "SUCCEEDED"
        text = "അക്നജ ഡിജിറ്റൽ പുതിയ ക്ലയന്റ് പോർട്ടൽ അവതരിപ്പിക്കും."
        provider = "indictrans2"
        model = "indictrans2-dist-200M"
        latency_ms = 123
        reason = ""

    def _fake_complete(dbb, **kwargs):
        assert kwargs["task"] == "translation", "portal must use task=translation"
        return _Result()

    if monkeypatch is not None:
        # gateway.py binds llm_complete at module import — patch the name the
        # gateway actually calls, not just the inference module attribute.
        from app.modules.ai import gateway as gateway_module
        from app.modules.ai import inference as inference_module

        monkeypatch.setattr(inference_module, "llm_complete", _fake_complete)
        monkeypatch.setattr(gateway_module, "llm_complete", _fake_complete)
    return AuthClient(app, "trans-owner@example.com", "TransPass#1")


def test_portal_translate_page_renders(db, app, seed) -> None:
    portal = _setup_portal(db, app, seed, None)
    resp = portal.get("/portal/translate")
    assert resp.status_code == 200
    assert "Translate" in resp.text
    assert "Malayalam" in resp.text
    assert "requests used today" in resp.text


def test_portal_translate_success_flow(db, app, seed, monkeypatch) -> None:
    portal = _setup_portal(db, app, seed, monkeypatch)
    resp = portal.post("/portal/translate", data={
        "source": "en", "target": "ml", "text": TEXT_EN, "csrf_token": portal.csrf,
    })
    assert resp.status_code == 200
    assert "അക്നജ" in resp.text
    assert "indictrans2" in resp.text

    from app.modules.governance.models import AuditEvent

    events = db.scalars(
        select(AuditEvent).where(AuditEvent.action == "portal.translate")
    ).all()
    assert len(events) == 1
    event = events[0]
    assert event.resource_type == "client"
    assert event.resource_id  # the client id — counted by the daily limit
    # the ledger stores only a hash of the payload: the raw text (and even
    # the metadata) is never persisted in readable form
    assert len(event.payload_hash) == 64
    assert event.payload_hash != canonical_payload_hash({"text": TEXT_EN})


def test_portal_translate_rejects_credentials(db, app, seed, monkeypatch) -> None:
    portal = _setup_portal(db, app, seed, monkeypatch)
    resp = portal.post("/portal/translate", data={
        "source": "en", "target": "ml",
        "text": "My API key is sk-abcdefghijklmnop1234567890 please translate",
        "csrf_token": portal.csrf,
    })
    assert resp.status_code == 200
    assert "NOT sent" in resp.text
    from app.modules.governance.models import AuditEvent

    assert db.scalars(
        select(AuditEvent).where(AuditEvent.action == "portal.translate")
    ).all() == []


def test_portal_translate_daily_limit(db, app, seed, monkeypatch) -> None:
    portal = _setup_portal(db, app, seed, monkeypatch)
    monkeypatch.setattr(
        "app.modules.ops.settings_service.get_setting",
        lambda dbb, key, default=None: 2 if key == "portal_translate_daily_limit" else default,
    )
    for _ in range(2):
        resp = portal.post("/portal/translate", data={
            "source": "en", "target": "ml", "text": "Translate me please",
            "csrf_token": portal.csrf,
        })
        assert "അക്നജ" in resp.text
    resp = portal.post("/portal/translate", data={
        "source": "en", "target": "ml", "text": "One more", "csrf_token": portal.csrf,
    })
    assert "Daily translation limit reached" in resp.text


def test_portal_translate_rejects_same_language(db, app, seed, monkeypatch) -> None:
    portal = _setup_portal(db, app, seed, monkeypatch)
    resp = portal.post("/portal/translate", data={
        "source": "en", "target": "en", "text": "Hello", "csrf_token": portal.csrf,
    })
    assert "must differ" in resp.text


def test_admin_cannot_use_portal_translate(db, app, seed, monkeypatch) -> None:
    """RBAC: portal-only page — staff sessions get the 403 boundary page."""
    _setup_portal(db, app, seed, monkeypatch)
    admin = AuthClient(app, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert admin.get("/portal/translate").status_code == 403


def test_portal_translate_rejects_non_english_pairs(db, app, seed, monkeypatch) -> None:
    """The indictrans2 worker contract is en<->{ml,hi,ta}: ml->hi must be
    rejected at the form, not surface as a worker 400 (live 2026-11-15)."""
    portal = _setup_portal(db, app, seed, monkeypatch)
    resp = portal.post("/portal/translate", data={
        "source": "ml", "target": "hi", "text": "സന്ദേശം", "csrf_token": portal.csrf,
    })
    assert "Supported pairs" in resp.text
