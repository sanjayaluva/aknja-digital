# Episodic memory — Telegram notification outbox (2026-11-14)

**Scope:** EPISODIC · **Sensitivity:** INTERNAL · **Approved:** yes (founder-reviewed)

## What was built

Durable admin-notification outbox (`notification_outbox` table +
`app/modules/ops/notifications.py`) for the founder Telegram channel,
ml|en templates, keyed by unique idempotency keys. docs/39 semantics:
delivery is provider-confirmed only on HTTP 200 + ok:true; 429 honors
`retry_after`, otherwise exponential backoff (60s · 2^attempts, capped 1h,
max 6 attempts); 400/403 (chat not found / bot blocked) is terminally
FAILED with no re-attempt; an unconfigured channel (token/chat unset)
keeps every row PENDING with attempts 0 — nothing is lost. Platform hooks:
approval.requested (by approval id), quota.hard_stop (per product per UTC
day), run.blocked (by run id, from the PENDING_MANUAL path). CLI:
`process-notifications`, `send-test-notification`.

## Lessons worth remembering

- Telegram sendMessage is not idempotent: after an uncertain timeout a
  retry can duplicate on the provider side. Every body carries a `· ref
  <key suffix>` footer so duplicates are identifiable and reconcilable.
- Concurrent quota workers can hit the same hard-stop alert key at the
  same moment: enqueue must use a SAVEPOINT (`db.begin_nested()`) so a
  lost unique-index race does not poison the admission transaction. The
  loser simply skips — the alert already exists. The quota concurrency
  tests (4×10 against cap 23.75) are the regression guard for this.
- httpx serializes JSON without spaces (`"chat_id":"42"`); assert on the
  compact form in mock handlers.
- The outbox row IS the delivery record — no per-send audit entries (the
  hash-chained audit ledger stays for governance events only).

**Provenance:** this round's commit; `tests/test_notifications.py` (13);
migration `c7d2e8f4a9b1` roundtrip check; docs/39, docs/26, runbook §12.
