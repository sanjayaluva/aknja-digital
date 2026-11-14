# AI Execution State Machine

`OBSERVE → PLAN → POLICY_CHECK → EXECUTE_LOW_RISK / WAITING_APPROVAL → EXECUTE_APPROVED → VERIFY → PERSIST → CONTINUE`.

Other states: `BLOCKED`, `RETRY_WAIT`, `QUARANTINED`, `ROLLBACK`, `FAILED`, `CANCELLED`.

Every transition has preconditions, actor, timestamp, idempotency key, side effects, retry policy and audit record. A model response is not a successful action; only a Tool Gateway result plus verification can mark execution complete.
