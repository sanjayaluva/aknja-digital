# AI Execution State Machine

`OBSERVE → PLAN → POLICY_CHECK → EXECUTE_LOW_RISK / WAITING_APPROVAL → EXECUTE_APPROVED → VERIFY → PERSIST → CONTINUE`.

Other states: `BLOCKED`, `RETRY_WAIT`, `QUARANTINED`, `ROLLBACK`, `FAILED`, `CANCELLED`.

Every transition has preconditions, actor, timestamp, idempotency key, side effects, retry policy and audit record. A model response is not a successful action; only a Tool Gateway result plus verification can mark execution complete.

## LLM steps (v5.3.2 §5C, implemented 2026-11-14)

`execute_llm_step` runs model work only in `PLAN`, `EXECUTE_LOW_RISK` or
`EXECUTE_APPROVED`, only for capabilities that allow `llm.generate`, and only
with PUBLIC/INTERNAL run data. Outcome mapping:

- `SUCCEEDED` → run event + audit; the run stays in its execution state and
  the caller moves it to `VERIFY` with the step output (never auto-COMPLETED).
- `PENDING_MANUAL` (no eligible free provider) → `BLOCKED` (founder review
  queue); from `EXECUTE_APPROVED` → `RETRY_WAIT`, because `BLOCKED` is not
  reachable from there. Never a silent degrade, never a paid fallback.
- `FAILED` (all eligible providers exhausted) → `RETRY_WAIT`.
- CONFIDENTIAL/RESTRICTED run data → `BLOCKED` before any egress.

