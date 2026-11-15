"""Zero-hardcode system settings engine (SRS v5.2 §8.1-8.2).

All business/operational parameters live here — never in code. Saving a
setting validates the type, writes an audit event and invalidates the
in-process cache. Protected governance invariants (zero-cost mode, spend
ceiling, tenant isolation, approval rules) are NOT settings and cannot be
weakened through this table (see .aknja/policies/protected-governance.md).
"""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationAppError
from app.modules.identity.service import Principal
from app.modules.ops.models import SystemSetting

# Seeded defaults, transcribed from SRS v5.2 §8.2 Tab 1-7 (preserved baseline).
# (key, category/tab, value, value_type, description)
SEEDED_SETTINGS: list[tuple[str, str, Any, str, str]] = [
    # Tab 1 — Brand, Domain & Agency Master Identities
    ("brand_name", "brand", "Aknja Digital", "string", "UI headers, portals, proposals, emails"),
    ("legal_billing_name", "brand", "Aknja Software Solutions", "string", "Invoices, contracts, tax declarations"),
    ("public_domain", "brand", "aknja.pp.ua", "string", "Portal URLs, webhooks, SEO canonicals, email aliases"),
    ("agency_master_aliases", "brand", {"ops": "ops@aknja.pp.ua", "projects": "projects@aknja.pp.ua", "leads": "leads@aknja.pp.ua", "billing": "billing@aknja.pp.ua"}, "json", "Auto-regenerates on public_domain change unless overridden"),
    ("brand_logo_key", "brand", "branding/aknja-digital-logo.svg", "string", "Client portal and PDF branding"),
    ("business_address", "brand", "Poikkattussery, Aluva, Ernakulam, Kerala, India", "string", "Invoices, contracts, legal footers"),
    ("udyam_reg_number", "brand", "KL02D0023222", "string", "Invoices, MSME verification blocks"),
    ("tax_pan_number", "brand", "", "string", "Indian client invoices & payment gateway KYC"),
    ("default_admin_language", "brand", "ml", "enum", "Telegram digest language & Admin UI default locale (ml|en)"),
    # Tab 2 — Commercial, Contract, Invoicing & Tax
    ("warranty_days", "commercial", 30, "int", "Proposals, contracts, post-handoff warranty timers"),
    ("payment_milestone_split", "commercial", [30, 30, 40], "json", "Milestone invoice percentages (Advance/Staging UAT/Final)"),
    ("quote_validity_days", "commercial", 15, "int", "Proposal & quotation expiry"),
    ("free_revision_rounds", "commercial", 2, "int", "Contract terms & scope-creep guard baseline"),
    ("primary_domestic_currency", "commercial", "INR", "string", "Domestic billing (minor units)"),
    ("international_marketplace_currency", "commercial", "USD", "string", "International billing (minor units)"),
    ("tax_mode", "commercial", "NON_GST_EXEMPT", "enum", "NON_GST_EXEMPT | GST_REGISTERED"),
    ("gstin_number", "commercial", "", "string", "Activated automatically when tax_mode=GST_REGISTERED"),
    ("default_sac_code", "commercial", "998314", "string", "IT design & development SAC code on invoices"),
    ("invoice_prefix", "commercial", "AKN-2026-", "string", "Sequential invoice numbering prefix"),
    ("payment_bank_upi_details", "commercial", {"bank_name": "", "account_name": "Aknja Software Solutions", "account_no": "", "ifsc": "", "upi_id": "", "wise_handle": ""}, "json", "Rendered on generated invoices & payment links"),
    # Tab 3 — AI Scheduler, Failover & Quota Controls
    ("soft_switch_threshold_pct", "ai_quota", 85.0, "float", "Pre-flight router proactive key rotation threshold"),
    ("gpu_checkpoint_interval_min", "ai_quota", 10, "int", "Layer-4 batch compute checkpoint interval"),
    ("default_max_retries", "ai_quota", 3, "int", "Cross-layer retry count before task quarantine"),
    ("quota_resume_buffer_sec", "ai_quota", 30, "int", "Cooldown window after HTTP 429/5xx circuit trip"),
    ("exhaust_free_first_strict_mode", "ai_quota", True, "bool", "100% free-pool utilization before any paid adapter"),
    # Tab 4 — Automated QA Gates
    ("min_pytest_coverage_pct", "qa_gates", 80, "int", "CI/CD & PR merge gate minimum coverage"),
    ("min_critic_ai_score", "qa_gates", 85, "int", "Minimum AI critic review score (0-100)"),
    ("enforce_ruff_zero_errors", "qa_gates", True, "bool", "Block PRs with lint violations"),
    ("enforce_docs_sync_gate", "qa_gates", True, "bool", "Require docs/ updates on schema/API branches"),
    ("self_evolution_healthz_rollback_sec", "qa_gates", 15, "int", "Auto-rollback timeout if /healthz fails after self-update"),
    # Tab 5 — HITL Approval Gates
    ("hitl_gate_overrides", "hitl", {"FREELANCE_PROPOSAL_SEND": True, "FREELANCE_CHAT_REPLY": True, "SCOPE_DECOMPOSITION": True, "CHANGE_REQUEST_QUOTE": True, "WIREFRAME_DESIGN": True, "CAMPAIGN_LAUNCH": True, "STAGING_DELIVERABLE": True, "CLIENT_OUTBOUND_COMMS": True, "PRODUCTION_CUTOVER": True}, "json", "Per-gate ON/OFF toggle for approval vs auto-approve"),
    ("tts_voice_en", "hitl", "en-IN-NeerjaNeural", "string", "Default English neural voice"),
    ("tts_voice_ml", "hitl", "ml-IN-SobhanaNeural", "string", "Default Malayalam neural voice"),
    # Tab 6 — Freelance Marketplace Bridge Rules
    ("min_feasibility_score_threshold", "leads", 70, "int", "Minimum score (0-100) to notify founder & draft bid"),
    ("preferred_interview_likelihood", "leads", "LOW", "enum", "LOW | MEDIUM | ANY"),
    ("scope_creep_sensitivity", "leads", "STRICT", "enum", "STRICT | BALANCED | FLEXIBLE"),
    ("enabled_marketplaces", "leads", ["UPWORK", "FIVERR", "FREELANCER_COM", "GURU_COM", "CONTRA", "REDDIT_FORHIRE"], "json", "Active ingestion adapters (read-only, anti-ban guard)"),
    ("anti_ban_guard_locked", "leads", True, "bool", "Locks read-only ingestion compliance"),
    # Tab 7 — SDLC & DMLC Default Modes
    ("default_asset_intake_mode", "sdlc", "ZERO_ASSET_STARTUP", "enum", "ZERO_ASSET_STARTUP | CLIENT_PROVIDED"),
    ("default_wireframe_mode", "sdlc", "STANDARD_TEMPLATE", "enum", "STANDARD_TEMPLATE | CUSTOM_UI"),
    ("client_kyc_reminder_interval_hours", "sdlc", 24, "int", "Reminder cadence for BLOCKED_ON_CLIENT_KYC projects"),
    ("dmlc_ab_evaluation_window_days", "sdlc", 5, "int", "Ad creative A/B evaluation duration"),
    ("whatsapp_daily_warmup_limit", "sdlc", 50, "int", "Max daily outbound WhatsApp messages"),
    # Tab 8 — Operations & Recovery (v5.3.2 §5A, docs/22)
    ("maintenance_mode_enabled", "ops_recovery", False, "bool",
     "Write freeze: when true the app serves read-only (controlled promotion / quota exhaustion)"),
    ("maintenance_reason", "ops_recovery", "", "string",
     "Shown in 503 responses and the founder notification when maintenance mode activates"),
    ("backup_max_age_hours", "ops_recovery", 26, "int",
     "Freshness SLO for the newest backup (backup verify --max-age monitors this)"),
]

# Settings that must never be user-editable at runtime (protected names).
PROTECTED_KEYS = {"anti_ban_guard_locked"}

_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()
_cache_loaded = False


def seed_settings(db: Session) -> int:
    """Insert any missing seeded default (idempotent)."""
    created = 0
    existing = {s.key for s in db.scalars(select(SystemSetting))}
    for key, category, value, value_type, description in SEEDED_SETTINGS:
        if key in existing:
            continue
        db.add(
            SystemSetting(
                key=key,
                category=category,
                value_json=value,
                value_type=value_type,
                description=description,
            )
        )
        created += 1
    if created:
        db.flush()
    invalidate_cache()
    return created


def _validate(value: Any, value_type: str) -> Any:
    if value_type == "string":
        if not isinstance(value, str):
            raise ValidationAppError("value must be a string")
    elif value_type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationAppError("value must be an integer")
    elif value_type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationAppError("value must be a number")
    elif value_type == "bool":
        if not isinstance(value, bool):
            raise ValidationAppError("value must be a boolean")
    elif value_type == "json":
        if not isinstance(value, (dict, list)):
            raise ValidationAppError("value must be a JSON object or array")
    elif value_type == "enum":
        if not isinstance(value, str):
            raise ValidationAppError("value must be a string")
    else:
        raise ValidationAppError(f"Unknown value_type '{value_type}'")
    return value


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    _ensure_cache(db)
    return _cache.get(key, default)


def get_all_settings(db: Session) -> list[SystemSetting]:
    return list(db.scalars(select(SystemSetting).order_by(SystemSetting.category, SystemSetting.key)))


def update_setting(
    db: Session, *, principal: Principal, key: str, value: Any
) -> SystemSetting:
    setting = db.get(SystemSetting, key)
    if setting is None:
        raise NotFoundError(f"Setting '{key}' does not exist")
    if key in PROTECTED_KEYS:
        raise ValidationAppError(f"Setting '{key}' is protected and cannot be changed at runtime")
    old = setting.value_json
    setting.value_json = _validate(value, setting.value_type)
    setting.updated_by = principal.user_id
    db.flush()
    # Audit every settings mutation (SRS §8.1).
    from app.modules.governance.service import record_audit

    record_audit(
        db,
        tenant_id=principal.tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action="settings.updated",
        resource_type="system_setting",
        resource_id=key,
        payload={"old": old, "new": value},
    )
    invalidate_cache()
    return setting


def _ensure_cache(db: Session) -> None:
    global _cache_loaded
    if _cache_loaded:
        return
    with _cache_lock:
        if _cache_loaded:
            return
        for s in db.scalars(select(SystemSetting)):
            _cache[s.key] = s.value_json
        _cache_loaded = True


def invalidate_cache() -> None:
    """Immediate invalidation on save (SRS §8.1: instant propagation)."""
    global _cache_loaded
    with _cache_lock:
        _cache.clear()
        _cache_loaded = False


def get_settings_by_category(db: Session) -> dict[str, list[SystemSetting]]:
    grouped: dict[str, list[SystemSetting]] = {}
    for s in get_all_settings(db):
        grouped.setdefault(s.category, []).append(s)
    return grouped
