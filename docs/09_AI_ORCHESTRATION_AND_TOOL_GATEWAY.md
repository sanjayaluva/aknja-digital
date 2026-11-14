# AI Orchestration and Tool Gateway

## Orchestrator loop
Resolve tenant/project/environment → load policy and approved context → classify data → interpret goal → plan DAG → estimate resource/quota → check tools/permissions → request approvals → dispatch bounded worker → collect structured result → independently verify → persist evidence/state → continue or block.

## Tool Gateway checks
- authenticated actor and tenant scope;
- project/environment scope;
- tool allow-list and argument schema;
- data classification and destination;
- approval record and payload hash;
- quota permit and spend policy;
- idempotency key and replay protection;
- rate limit and timeout;
- audit event before/after action.

## Worker contract
Input: task ID, objective, context references, acceptance criteria, allowed tools, budget/time, data classification.  
Output: status, summary, artifacts, test/evidence references, risks, unresolved questions, usage and proposed next actions.

No worker can approve itself, modify governance, access arbitrary secrets or deploy production.
