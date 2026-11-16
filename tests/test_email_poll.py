"""Email ingestion tests (docs/34, T-028)."""

from __future__ import annotations

import email
import email.policy
import email.utils
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.crm.models import Lead
from app.modules.identity.service import Principal
from app.modules.integrations import service as integrations
from app.modules.integrations.email_poll import poll_email_inbox
from app.modules.intake.models import IntakeMessage


def _principal(seed) -> Principal:
    return Principal(user_id=seed.admin.id, email=seed.admin.email,
                     tenant_id=seed.tenant.id, role=UserRole.SUPER_ADMIN,
                     client_id=None, session_id=seed.admin.id, csrf_token="t")


def _mime(subject: str, body: str, when: datetime) -> bytes:
    msg = email.message_from_string(
        f"From: Ravi <ravi@example.com>\n"
        f"To: requests@aknja.pp.ua\n"
        f"Subject: {subject}\n"
        f"Date: {email.utils.format_datetime(when)}\n"
        f"Message-ID: <{subject[:8]}@example.com>\n"
        f"\n{body}\n",
        policy=email.policy.default,
    )
    return msg.as_bytes()


class StubIMAP:
    """Minimal imaplib stand-in; records \\Seen marks as the poll cursor."""

    def __init__(self, messages: dict):
        self.messages = messages  # uid(bytes) -> raw bytes
        self.seen: list = []

    def login(self, user, password):
        assert user and password, "credentials must be complete"
        return ("OK", [b"Logged in"])

    def select(self, folder, readonly=False):
        return ("OK", [b"1"])

    def search(self, charset, criteria):
        return ("OK", [b" ".join(self.messages.keys())])

    def fetch(self, uid, spec):
        return ("OK", [(b"1 (RFC822 {256}", self.messages[uid]), b")"])

    def store(self, uid, op, flags):
        self.seen.append(uid)
        return ("OK", [b"1"])

    def logout(self):
        return ("BYE", [b""])


def _register_gmail(db, seed):
    _principal(seed)
    integrations.save_credential(
        db, principal=_principal(seed), provider_key="gmail", provider_type="EMAIL",
        name="System Gmail", secrets={"username": "aknja.system@gmail.com",
                                      "app_password": "fake-app-pw"},
        config={"imap_host": "imap.gmail.com", "imap_port": 993})
    row = db.scalar(select(integrations.IntegrationCredential).where(
        integrations.IntegrationCredential.provider_key == "gmail"))
    integrations.set_status(db, principal=_principal(seed),
                            credential_id=row.id, status="ACTIVE")
    db.commit()
    return row


def test_poll_feeds_inbox_into_intake_and_marks_seen(db, seed, monkeypatch):
    import app.modules.intake.service as intake_svc
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    old = datetime.now(timezone.utc) - timedelta(days=30)
    stub = StubIMAP({
        b"1": _mime("Website needed", "I need a bakery website with online "
                                      "ordering. Budget 20000 rupees.", recent),
        b"2": _mime("Ancient thread", "old mail must be skipped", old),
    })
    monkeypatch.setattr(intake_svc, "llm_complete", lambda *a, **k: SimpleNamespace(
        status="SUCCEEDED", provider="groq",
        text=('{"is_project_inquiry": true, "service_domain": "SOFTWARE_ENGINEERING", '
              '"language": "en", "urgency": "normal", "summary": "bakery website"}'),
        reason=""))
    # extraction lane: reuse classification stub shape via task switch
    def fake_llm(db_, *, tenant_id, task, prompt, **kw):
        if task == "requirements":
            return SimpleNamespace(
                status="SUCCEEDED", provider="groq", reason="",
                text=('{"requirements": ["bakery website", "online ordering"], '
                      '"missing_info": ["deadline"], "suggested_title": "Bakery Website"}'))
        return SimpleNamespace(
            status="SUCCEEDED", provider="groq", reason="",
            text=('{"is_project_inquiry": true, "service_domain": "SOFTWARE_ENGINEERING", '
                  '"language": "en", "urgency": "normal", "summary": "bakery website"}'))
    monkeypatch.setattr(intake_svc, "llm_complete", fake_llm)

    _register_gmail(db, seed)
    summary = poll_email_inbox(
        db, tenant_id=seed.tenant.id, settings=Settings(),
        imap_factory=lambda host, port: stub)
    db.commit()

    assert summary["fetched"] == 1  # the old mail was skipped, not ingested
    assert summary["converted"] == 1
    assert sorted(stub.seen) == [b"1", b"2"]  # both marked seen (cursor)
    msg = db.scalars(select(IntakeMessage).where(
        IntakeMessage.channel == "EMAIL")).all()
    assert len(msg) == 1 and msg[0].status == "CONVERTED"
    assert "ravi@example.com" in msg[0].raw_content
    assert msg[0].sender == "ravi@example.com"
    lead = db.get(Lead, msg[0].lead_id)
    assert lead.source == "EMAIL" and lead.contact_email == "ravi@example.com"


def test_poll_noop_without_active_credential(db, seed):
    summary = poll_email_inbox(db, tenant_id=seed.tenant.id, settings=Settings())
    assert summary["providers"] == 0 and summary["fetched"] == 0


def test_poll_records_provider_failure_without_crashing(db, seed):
    def broken_factory(host, port):
        raise OSError("DNS failure")

    _register_gmail(db, seed)
    summary = poll_email_inbox(
        db, tenant_id=seed.tenant.id, settings=Settings(),
        imap_factory=broken_factory)
    assert summary["fetched"] == 0
    assert any("connect failed" in e for e in summary["errors"])
