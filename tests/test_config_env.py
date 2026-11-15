"""Config env-name mapping tests (docs/39 + founder credential sheet).

The founder's credential sheet names the alert recipient
TELEGRAM_FOUNDER_CHAT_ID while docs/39 documents TELEGRAM_ADMIN_CHAT_ID —
Settings accepts both (AliasChoices) and stays constructible by field name
(populate_by_name, the pattern used by every notification test helper).
"""

from __future__ import annotations

from app.core.config import Settings


def _clean_env(monkeypatch) -> None:
    for name in ("TELEGRAM_ADMIN_CHAT_ID", "TELEGRAM_FOUNDER_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)


def test_founder_chat_id_env_maps_to_admin_chat_id(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_FOUNDER_CHAT_ID", "99182736")
    cfg = Settings(_env_file=None)
    assert cfg.telegram_admin_chat_id == "99182736"


def test_admin_chat_id_env_still_works(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "424242")
    cfg = Settings(_env_file=None)
    assert cfg.telegram_admin_chat_id == "424242"


def test_field_name_construction_still_works() -> None:
    # The tests/test_notifications.py _settings() helper pattern: kwargs use
    # the field name even though the field now carries a validation_alias.
    cfg = Settings(_env_file=None, telegram_admin_chat_id="777")
    assert cfg.telegram_admin_chat_id == "777"
